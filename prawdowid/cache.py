"""Source cache and step 2c: every page fetched by web search, and full-text search over them.

With `DATABASE_URL` set (local PostgreSQL from compose.yaml, schema in `db/migrations/`) pages go
to the `documents` and `chunks` tables and `search_documents` searches them per claim. Without it
pages go to the local JSONL file `corpus/docs.jsonl` (ignored by git: full page text, not
redistributed) and the database search reports itself unavailable, so the check goes on with
steps 2a and 2b. The JSONL line format (`url`, `text`, ...) is what `evals.run --corpus` reads;
`prawdowid.corpus` exports the database to it.

Only web search (#8) calls `save_document`. Pages from links the user submits (#4) are never saved:
they are fetched with `websearch.fetch_document`, which does not save.

psycopg 3: a document and its chunks go in one transaction, and the ranked search is one SQL query.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from prawdowid.contract import Source
from prawdowid.privacy import mask_personal_data
from prawdowid.rerank import Fragment, canonical_url, split_text

log = logging.getLogger("prawdowid")

CACHE_PATH = Path(os.getenv("PRAWDOWID_CACHE") or "corpus/docs.jsonl")
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
CHUNKS_PER_SEARCH = 20
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
    text: str
    licence: str = LICENCE_UNCONFIRMED

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
    if os.getenv(DATABASE_ENV):
        with _db() as conn:
            rows = conn.execute(
                f"select {_COLUMNS} from documents where delete_after > now() order by id"
            )
            return [Document(**row) for row in rows]
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [Document.model_validate_json(line) for line in f if line.strip()]


def save_document(doc: Document, path: Path = CACHE_PATH) -> bool:
    """Store the document unless its URL is stored already. True when it was added.

    A database failure is logged and returns False: losing one cached page never fails a check.
    """
    if os.getenv(DATABASE_ENV):
        try:
            return _insert(doc)
        except psycopg.Error as exc:
            log.warning("source store save failed %s: %r", doc.url, exc)
            return False
    # ponytail: rereads the file on every save; fine for a local demo cache.
    if any(d.url == doc.url for d in load_documents(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(doc.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return True


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
            rows = await _search_with_retry(query)
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

SEARCH_SQL = """
    select d.doc_id, d.url, d.title, d.publisher, d.source_type, d.published_at,
           d.fetched_at, c.text as fragment
    from chunks c
    join documents d on d.id = c.document_id,
         to_tsquery('simple', %(query)s) q
    where c.tsv @@ q and d.delete_after > now()
    order by ts_rank(c.tsv, q) desc
    limit %(limit)s
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
                doc.licence,
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


def _search(query: str) -> list[dict]:
    with _db() as conn:
        return conn.execute(
            SEARCH_SQL, {"query": query, "limit": CHUNKS_PER_SEARCH}
        ).fetchall()


async def _search_with_retry(query: str) -> list[dict] | None:
    """Blocking psycopg call in a thread, one retry. None when every attempt failed."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(_search, query)
        except psycopg.Error as exc:
            log.warning("database search attempt %d failed: %r", attempt, exc)
    return None
