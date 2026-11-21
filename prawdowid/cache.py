"""Source cache, and step 2c: our own PostgreSQL store with full-text search.

Step 2c is **disabled in the pipeline** (user decision, 2026-11-21) until the team chooses licensed
sources: checks never write to the database and nothing in `verify()` calls `search_documents`.

Local JSONL cache `corpus/docs.jsonl` (`save_document`, `load_documents`, `delete_document`): the
pages web search read. What is kept (brief: no archiving of full content without a legal basis,
licence, retention, access control and deletion):
- Metadata of every page: URL, title, publisher, dates, source type, domain, licence.
- Full text only when the domain's licence is confirmed (`Domain.licence` in websearch.py).
  Today none is, so `text` is stored empty. The pipeline still uses the live text in memory.
- Retention: records older than `RETENTION_DAYS` (by `fetched_at`) are dropped on every save;
  `delete_document(url)` removes one record, deleting the file removes everything.
- Access: owner read/write only (0600), ignored by git. A URL keeps one record (latest fetch).
The line format (`url`, `text`, ...) is what `evals.run --corpus` reads.

PostgreSQL store (`DATABASE_URL`, schema in `db/migrations/`):
- `store_document` / `stored_documents`: only the seed script `prawdowid.corpus` writes to it.
  Page text from the database is never exported, so its retention and deletion cover every copy.
- `search_documents(claim)`: per-claim search of the store for rerank (#9). Without `DATABASE_URL`,
  or when the database fails, it returns the "database unavailable" limitation, never a verdict.

Pages from links the user submits (#4) are never saved: `websearch.fetch_document` does not save.
psycopg 3: a document and its chunks go in one transaction, and the ranked search is one SQL query.
"""

import asyncio
import hashlib
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from prawdowid.contract import Source
from prawdowid.privacy import mask_personal_data
from prawdowid.rerank import Fragment, canonical_url, split_text

log = logging.getLogger("prawdowid")

CACHE_PATH = Path(os.getenv("PRAWDOWID_CACHE") or "corpus/docs.jsonl")
RETENTION_DAYS = 30
DATABASE_ENV = "DATABASE_URL"
LICENCE_UNCONFIRMED = "UNCONFIRMED (docs/sources.md)"

CONNECT_TIMEOUT_S = 4
STATEMENT_TIMEOUT_MS = 4000
SEARCH_DEADLINE_S = 15  # whole search, retry included
# A stalled socket after connect: the server-side statement timeout cannot fire, these do.
TCP_SETTINGS = {
    "keepalives_idle": 5,
    "keepalives_interval": 2,
    "keepalives_count": 2,
    "tcp_user_timeout": 10_000,  # ms; ignored where the OS has no TCP_USER_TIMEOUT
}
ATTEMPTS = 2  # first call plus one retry
# Best chunks kept per document, so one long page cannot crowd out the others.
CHUNKS_PER_DOCUMENT = 2
DOCUMENTS_PER_CLAIM = 5
MAX_TERMS = 12

DATABASE_UNAVAILABLE = (
    "Nasza baza źródeł była niedostępna, "
    "więc nie szukaliśmy w zapisanych wcześniej stronach."
)

# Frequent Polish words of 4+ letters that would match nearly every page.
STOPWORDS = frozenset(
    [
        "oraz",
        "jest",
        "przez",
        "tego",
        "które",
        "który",
        "która",
        "były",
        "było",
        "będzie",
        "jako",
        "także",
        "tylko",
        "może",
        "jego",
        "jednak",
        "przy",
        "więc",
        "żeby",
        "gdzie",
        "kiedy",
        "bardzo",
        "tych",
        "tym",
        "zostać",
        "został",
        "została",
    ]
)


class Document(BaseModel):
    url: str
    title: str
    publisher: str
    published_at: date
    fetched_at: datetime
    source_type: str
    domain: str
    licence: str | None = None
    text: str

    def to_source(self, fragment: str | None = None) -> Source:
        return Source(
            title=self.title,
            publisher=self.publisher,
            published_at=self.published_at,
            fetched_at=self.fetched_at,
            url=self.url,
            source_type=self.source_type,
            fragment=fragment,
        )


class DatabaseSearch(BaseModel):
    # One item per document, most relevant first; `doc_id` is the canonical URL rerank keys on.
    fragments: list[Fragment] = []
    # Set when the database could not be searched; goes to ClaimResult.limitations.
    limitation: str | None = None


def load_documents(path: Path = CACHE_PATH) -> list[Document]:
    """Records within retention. Expired ones are never returned, even before the next save."""
    if not path.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    with path.open(encoding="utf-8") as f:
        docs = [Document.model_validate_json(line) for line in f if line.strip()]
    return [d for d in docs if d.fetched_at >= cutoff]


def save_document(doc: Document, path: Path = CACHE_PATH) -> None:
    """Store the latest fetch of this URL (text only if licensed) and drop expired records."""
    kept = [d for d in load_documents(path) if d.url != doc.url]
    _write(path, [*kept, doc])


def delete_document(url: str, path: Path = CACHE_PATH) -> bool:
    """Remove the record of this URL. True when there was one."""
    docs = load_documents(path)
    kept = [d for d in docs if d.url != url]
    _write(path, kept)
    return len(kept) < len(docs)


def _write(path: Path, docs: list[Document]) -> None:
    """Rewrite the file. Text of unlicensed records is dropped here, old records included."""
    # ponytail: whole-file rewrite, one writer process at a time (two concurrent savers can
    # lose a record). Fine for the demo corpus; the Supabase store (#19) replaces it.
    docs = [d if d.licence else d.model_copy(update={"text": ""}) for d in docs]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(d.model_dump_json() + "\n" for d in docs)
    tmp.replace(path)


def stored_documents() -> list[Document]:
    """Every unexpired document in the database."""
    with _db() as conn:
        rows = conn.execute(
            f"select {_COLUMNS} from documents where delete_after > now() order by id"
        )
        return [Document(**row) for row in rows]


def store_document(doc: Document) -> bool:
    """Insert the document and its chunks unless its doc id is stored. True when it was added.

    A database failure is logged and returns False: losing one page never stops the seed.
    """
    try:
        return _insert(doc)
    except psycopg.Error as exc:
        log.warning("source store save failed: %s", type(exc).__name__)
        return False


def delete_expired() -> int:
    """Retention: delete pages past `delete_after`. Number of documents deleted."""
    with _db() as conn:
        return conn.execute("select delete_expired_documents() as n").fetchone()["n"]


async def search_documents(
    claim: str, *, limit: int = DOCUMENTS_PER_CLAIM
) -> DatabaseSearch:
    """Step 2c for one claim: stored pages matching its words, best first."""
    if not os.getenv(DATABASE_ENV):
        log.warning("database search skipped: %s is not set", DATABASE_ENV)
        return DatabaseSearch(limitation=DATABASE_UNAVAILABLE)
    query = build_tsquery(claim)
    if not query:
        return DatabaseSearch()
    try:
        async with asyncio.timeout(SEARCH_DEADLINE_S):
            rows = await _search_with_retry(query, limit)
    except TimeoutError:
        log.warning("database search unavailable: over %d s", SEARCH_DEADLINE_S)
        return DatabaseSearch(limitation=DATABASE_UNAVAILABLE)
    if rows is None:
        return DatabaseSearch(limitation=DATABASE_UNAVAILABLE)
    return DatabaseSearch(fragments=group_by_document(rows)[:limit])


def build_tsquery(claim: str) -> str | None:
    """OR of prefix terms from the claim's words, for to_tsquery('simple', ...).

    Only letters and digits reach the query, so tsquery syntax in the claim cannot change it.
    """
    # Placeholders such as "[telefon]" would become noise terms: drop them.
    masked = re.sub(r"\[[^\]]*\]", " ", mask_personal_data(claim))
    words = re.findall(r"[^\W_]+", masked.casefold())
    terms = dict.fromkeys(
        _prefix(w) for w in words if len(w) >= 4 and w not in STOPWORDS
    )
    return " | ".join(f"{t}:*" for t in list(terms)[:MAX_TERMS]) or None


def _prefix(word: str) -> str:
    """Crude stem: the 'simple' config does not stem, Polish inflects endings.

    ponytail: prefix cut, no real Polish stemmer; a hunspell/stempel dictionary if recall is poor.
    """
    if word.isdigit():
        return word
    return word[:6] if len(word) > 6 else word[:-1]


def group_by_document(rows: list[dict]) -> list[Fragment]:
    """Chunks ranked best first to one item per document; its matching chunks joined in order."""
    by_doc: dict[str, Fragment] = {}
    for row in rows:
        if hit := by_doc.get(row["doc_id"]):
            hit.source.fragment += "\n\n" + row["fragment"]
            continue
        source = Source(
            **{k: row[k] for k in Source.model_fields if k in row and k != "fragment"},
            fragment=row["fragment"],
        )
        by_doc[row["doc_id"]] = Fragment(doc_id=row["doc_id"], source=source)
    return list(by_doc.values())


_COLUMNS = "url, title, publisher, published_at, fetched_at, source_type, domain, text, licence"

# At most CHUNKS_PER_DOCUMENT chunks per document, then the best `limit` documents by their best
# chunk. Chunks come back best document first, each document's chunks in rank order.
SEARCH_SQL = """
    with ranked as (
        select c.document_id, c.text, ts_rank(c.tsv, q) as rank,
               row_number() over (partition by c.document_id order by ts_rank(c.tsv, q) desc, c.position) as n
        from chunks c, to_tsquery('simple', %(query)s) q
        where c.tsv @@ q
    ), best as (
        select d.id, max(r.rank) as best_rank
        from ranked r join documents d on d.id = r.document_id
        where d.delete_after > now()
        group by d.id
        order by best_rank desc, d.id
        limit %(documents)s
    )
    select d.doc_id, d.url, d.title, d.publisher, d.source_type, d.published_at,
           d.fetched_at, r.text as fragment
    from best b
    join documents d on d.id = b.id
    join ranked r on r.document_id = b.id and r.n <= %(per_document)s
    order by b.best_rank desc, d.id, r.n
"""


@contextmanager
def _db() -> Iterator[psycopg.Connection]:
    """One connection per call, one transaction, every statement bounded.

    prepare_threshold=None: no server-side prepared statements, so a pooler such as PgBouncer in
    transaction mode works too.
    """
    with psycopg.connect(
        os.environ[DATABASE_ENV],
        connect_timeout=CONNECT_TIMEOUT_S,
        prepare_threshold=None,
        **TCP_SETTINGS,
        row_factory=dict_row,
    ) as conn:
        conn.execute(f"set local statement_timeout = {STATEMENT_TIMEOUT_MS}")
        yield conn


def _insert(doc: Document) -> bool:
    with _db() as conn:
        row = conn.execute(
            """insert into documents (doc_id, url, title, publisher, domain, source_type,
                   licence, published_at, fetched_at, content_hash, text)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (doc_id) do nothing returning id""",
            (
                canonical_url(doc.url),
                doc.url,
                doc.title,
                doc.publisher,
                doc.domain,
                doc.source_type,
                doc.licence or LICENCE_UNCONFIRMED,
                doc.published_at,
                doc.fetched_at,
                hashlib.sha256(doc.text.encode()).hexdigest(),
                doc.text,
            ),
        ).fetchone()
        if row is None:
            return False
        chunks = [c for c in split_text(doc.text) if c]
        conn.cursor().executemany(
            "insert into chunks (document_id, position, text) values (%s, %s, %s)",
            [(row["id"], i, c) for i, c in enumerate(chunks)],
        )
        return True


def _search(query: str, documents: int) -> list[dict]:
    params = {
        "query": query,
        "documents": documents,
        "per_document": CHUNKS_PER_DOCUMENT,
    }
    with _db() as conn:
        return conn.execute(SEARCH_SQL, params).fetchall()


async def _search_with_retry(query: str, documents: int) -> list[dict] | None:
    """Blocking psycopg call in a thread, one retry. None when every attempt failed."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(_search, query, documents)
        except psycopg.Error as exc:
            log.warning(
                "database search attempt %d failed: %s", attempt, type(exc).__name__
            )
    return None
