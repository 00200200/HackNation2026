"""Load `corpus/evidence.jsonl` into Postgres for search: one row per document, its text cut into
chunks with an embedding (pgvector, HNSW index) and a full-text vector (GIN index).

Usage: DATABASE_URL=postgresql://... uv run python -m prawdowid.index [corpus/evidence.jsonl]

Incremental: a document whose content did not change keeps its chunks, a document no longer in
the file is deleted. Changing the embedding model rebuilds every chunk.
"""

import hashlib
import json
import logging
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from prawdowid import embeddings

log = logging.getLogger("prawdowid")

DOCS_PATH = Path("corpus/evidence.jsonl")
CHUNK_CHARS = 1200  # well inside the model's 512 tokens; long laws and articles get several chunks
DOCS_PER_BATCH = 64

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS corpus_meta (key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE IF NOT EXISTS corpus_documents (
    id text PRIMARY KEY,
    url text NOT NULL,
    title text NOT NULL,
    publisher text NOT NULL,
    published_at timestamptz,
    retrieved_at timestamptz NOT NULL,
    source_type text NOT NULL,
    source_id text NOT NULL,
    licence text NOT NULL,
    rating text,
    claim text,
    record jsonb NOT NULL,
    content_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS corpus_chunks (
    doc_id text NOT NULL REFERENCES corpus_documents (id) ON DELETE CASCADE,
    ord int NOT NULL,
    text text NOT NULL,
    embedding vector({dim}) NOT NULL,
    tsv tsvector NOT NULL,
    PRIMARY KEY (doc_id, ord)
);
CREATE INDEX IF NOT EXISTS corpus_chunks_embedding_idx ON corpus_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS corpus_chunks_tsv_idx ON corpus_chunks USING gin (tsv);
"""


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Consecutive pieces of at most `limit` characters, cut at line breaks, else at spaces.
    Each piece is a verbatim part of `text`, so a quote taken from a chunk is found in the
    document too."""
    pieces: list[str] = []
    for line in text.split("\n"):
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(line[:cut])
            line = line[cut:].lstrip(" ")
        pieces.append(line)  # empty lines too, so joined pieces stay verbatim
    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + 1 + len(piece) <= limit:
            chunks[-1] += "\n" + piece
        else:
            chunks.append(piece)
    return [c.strip("\n") for c in chunks if c.strip()]


def content_hash(record: dict) -> str:
    """What the chunks and their embeddings depend on: a new retrieval date alone changes nothing."""
    return hashlib.sha256(f"{record['title']}\n{record['text']}".encode()).hexdigest()


def ensure_schema(conn: psycopg.Connection, model: str, dim: int) -> None:
    """Create the tables; drop them first when they were built with another model."""
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    built_with = None
    if conn.execute("SELECT to_regclass('corpus_meta')").fetchone()[0]:
        row = conn.execute(
            "SELECT value FROM corpus_meta WHERE key = 'model'"
        ).fetchone()
        built_with = row[0] if row else None
    if built_with and built_with != model:
        log.warning("index was built with %s, rebuilding for %s", built_with, model)
        conn.execute("UPDATE corpus_meta SET value = 'false' WHERE key = 'complete'")
        conn.execute("DROP TABLE IF EXISTS corpus_chunks, corpus_documents")
    conn.execute(SCHEMA.format(dim=dim))
    conn.execute(
        "INSERT INTO corpus_meta VALUES ('model', %s) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (model,),
    )


def _batches(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


UPSERT_DOCUMENT = """
INSERT INTO corpus_documents VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    url = excluded.url, title = excluded.title, publisher = excluded.publisher,
    published_at = excluded.published_at, retrieved_at = excluded.retrieved_at,
    source_type = excluded.source_type, source_id = excluded.source_id,
    licence = excluded.licence, rating = excluded.rating, claim = excluded.claim,
    record = excluded.record, content_hash = excluded.content_hash
"""


def _document_row(r: dict) -> tuple:
    return (
        r["id"], r["url"], r["title"], r["publisher"], r["published_at"], r["retrieved_at"],
        r["source_type"], r["source_id"], r["licence"], r.get("rating"), r.get("claim"),
        json.dumps(r, ensure_ascii=False), content_hash(r),
    )  # fmt: skip


def _set_complete(conn: psycopg.Connection, complete: bool) -> None:
    conn.execute(
        "INSERT INTO corpus_meta VALUES ('complete', %s) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (str(complete).lower(),),
    )


def load(
    records: list[dict],
    conn: psycopg.Connection,
    *,
    embed: Callable[[list[str]], list[np.ndarray]] = embeddings.embed_passages,
    model: str | None = None,
    dim: int | None = None,
) -> dict[str, int]:
    """Bring the tables in line with `records`. Document rows are always refreshed; chunks are
    embedded again only when the title or text changed. Search reports the index as incomplete
    until the load finishes. Returns counts for the log."""
    model = model or embeddings.model_name()
    dim = dim or embeddings.dimension()
    ensure_schema(conn, model, dim)
    known = dict(
        conn.execute("SELECT id, content_hash FROM corpus_documents").fetchall()
    )
    gone = list(known.keys() - {r["id"] for r in records})
    changed = {r["id"] for r in records if known.get(r["id"]) != content_hash(r)}
    _set_complete(conn, False)
    with conn.transaction():
        conn.execute("DELETE FROM corpus_documents WHERE id = ANY(%s)", (gone,))
    chunk_count = done = 0
    for batch in _batches(records, DOCS_PER_BATCH):
        parts = [
            (r, i, c)
            for r in batch
            if r["id"] in changed
            for i, c in enumerate(chunk_text(r["text"]))
        ]
        vectors = embed([f"{r['title']}\n{c}" for r, _, c in parts]) if parts else []
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(UPSERT_DOCUMENT, [_document_row(r) for r in batch])
            cur.execute(
                "DELETE FROM corpus_chunks WHERE doc_id = ANY(%s)",
                ([r["id"] for r in batch if r["id"] in changed],),
            )
            cur.executemany(
                "INSERT INTO corpus_chunks VALUES (%s, %s, %s, %s,"
                " to_tsvector('simple', %s || ' ' || %s))",
                [
                    (r["id"], i, c, v, r["title"], c)
                    for (r, i, c), v in zip(parts, vectors, strict=True)
                ],
            )
        chunk_count += len(parts)
        done += len(batch)
        if parts:
            log.info("indexed %d of %d documents", done, len(records))
    _set_complete(conn, True)
    return {
        "documents": len(records),
        "changed": len(changed),
        "removed": len(gone),
        "chunks": chunk_count,
    }


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = Path(argv[1]) if len(argv) > 1 else DOCS_PATH
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with psycopg.connect(url, autocommit=True) as conn:
        counts = load(records, conn)
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
