import asyncio
import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import psycopg
import pytest

from prawdowid import cache, safefetch, websearch
from prawdowid.cache import (
    DATABASE_UNAVAILABLE,
    Document,
    build_tsquery,
    group_by_document,
    search_documents,
    store_document,
)
from prawdowid.rerank import split_all
from tests.test_websearch import html

FETCHED = datetime(2026, 11, 21, 12, tzinfo=UTC)


def row(url, fragment, **extra):
    return {
        "doc_id": url.removeprefix("https://www."),
        "url": url,
        "title": "Sankcje wobec Rosji",
        "publisher": "Rada UE",
        "source_type": "official",
        "published_at": date(2025, 6, 2),
        "fetched_at": FETCHED,
        "fragment": fragment,
        **extra,
    }


def doc(url="https://www.gov.pl/web/kas/sankcje"):
    return Document(
        url=url,
        title="Sankcje",
        publisher="KAS",
        published_at=date(2025, 6, 2),
        fetched_at=FETCHED,
        source_type="official",
        domain="www.gov.pl",
        text="Akapit pierwszy.\n\nAkapit drugi.",
    )


def connect_failing(calls):
    def connect(*args, **kwargs):
        calls.append(kwargs)
        raise psycopg.OperationalError("connection refused")

    return connect


def test_no_database_url_reports_database_unavailable():
    result = asyncio.run(search_documents("Rada UE przyjęła sankcje"))
    assert result.fragments == []
    assert result.limitation == DATABASE_UNAVAILABLE


def test_database_down_is_a_limitation_after_one_retry(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    calls = []
    monkeypatch.setattr(psycopg, "connect", connect_failing(calls))
    result = asyncio.run(search_documents("Rada UE przyjęła sankcje"))
    assert result.limitation == DATABASE_UNAVAILABLE
    assert len(calls) == cache.ATTEMPTS
    assert calls[0]["connect_timeout"] == cache.CONNECT_TIMEOUT_S


def test_slow_database_hits_the_deadline(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.setattr(cache, "SEARCH_DEADLINE_S", 0.05)
    monkeypatch.setattr(cache, "_search", lambda q, n: time.sleep(0.3) or [])
    result = asyncio.run(search_documents("Rada UE przyjęła sankcje"))
    assert result.limitation == DATABASE_UNAVAILABLE


def test_matching_document_comes_back_as_source_for_rerank(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    queries = []
    rows = [
        row("https://www.gov.pl/a", "Rada UE przyjęła pakiet sankcji."),
        row("https://www.nato.int/b", "NATO o sankcjach."),
        row("https://www.gov.pl/a", "Zakaz importu gazu."),
    ]
    monkeypatch.setattr(cache, "_search", lambda q, n: queries.append(q) or rows)
    result = asyncio.run(search_documents("Rada UE przyjęła sankcje wobec Rosji"))

    assert result.limitation is None
    assert [f.doc_id for f in result.fragments] == ["gov.pl/a", "nato.int/b"]
    first = result.fragments[0].source
    assert (first.title, first.publisher, first.published_at, str(first.url)) == (
        "Sankcje wobec Rosji",
        "Rada UE",
        date(2025, 6, 2),
        "https://www.gov.pl/a",
    )
    assert first.fragment == "Rada UE przyjęła pakiet sankcji.\n\nZakaz importu gazu."
    assert queries == [build_tsquery("Rada UE przyjęła sankcje wobec Rosji")]
    # Rerank (#9) splits the joined chunks again and keeps both documents.
    fragments = split_all([f.source for f in result.fragments], exclude_url=None)
    assert len(fragments) == 2


def test_query_keeps_content_words_as_prefixes_and_drops_syntax():
    query = build_tsquery(
        "Rada UE przyjęła sankcje wobec Rosji w 2024 roku, jest & !x:* |"
    )
    assert query == "rad:* | przyję:* | sankcj:* | wobe:* | rosj:* | 2024:* | rok:*"
    assert build_tsquery("UE, & | ! :*") is None


def test_query_masks_personal_data():
    query = build_tsquery("Dzwoń +48 600 100 200 w sprawie sankcji")
    assert "600" not in query and "telefo" not in query


def test_group_by_document_keeps_rank_order():
    fragments = group_by_document(
        [row("https://www.nato.int/b", "b1"), row("https://www.gov.pl/a", "a1")]
    )
    assert [f.source.fragment for f in fragments] == ["b1", "a1"]


def test_failed_database_save_never_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.setattr(psycopg, "connect", connect_failing([]))
    assert store_document(doc()) is False


class FakeConnection:
    def __init__(self, returned_id):
        self.returned_id = returned_id
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return None if self.returned_id is None else {"id": self.returned_id}

    def cursor(self):
        return self

    def executemany(self, sql, params):
        self.statements.append((sql, params))


def test_database_save_writes_document_and_chunks(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    conn = FakeConnection(returned_id=7)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: conn)
    assert (
        store_document(doc("http://www.gov.pl/web/kas/sankcje/?utm_source=x")) is True
    )

    timeout, insert, chunks = conn.statements
    assert "statement_timeout" in timeout[0]
    assert insert[1][0] == "https://gov.pl/web/kas/sankcje"  # canonical doc id
    assert insert[1][6] == cache.LICENCE_UNCONFIRMED
    assert chunks[1] == [(7, 0, "Akapit pierwszy.\n\nAkapit drugi.")]


def test_known_url_is_not_saved_twice(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    conn = FakeConnection(returned_id=None)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: conn)
    assert store_document(doc()) is False
    assert len(conn.statements) == 2  # no chunk insert


def test_checks_never_write_to_the_database(monkeypatch, tmp_path):
    """Step 2c is disabled: web search saves only to the JSONL cache, even with DATABASE_URL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.setattr(psycopg, "connect", connect_failing(calls := []))
    cache.save_document(doc(), tmp_path / "docs.jsonl")
    assert [d.url for d in cache.load_documents(tmp_path / "docs.jsonl")] == [doc().url]
    assert calls == []


def test_user_submitted_link_page_is_never_saved(monkeypatch):
    """#4 fetches a linked page with fetch_document: it must not reach the store."""
    saved = []
    monkeypatch.setattr(websearch, "save_document", saved.append)
    monkeypatch.setattr(cache, "save_document", saved.append)
    safefetch._robots.clear()

    async def go():
        transport = httpx2.MockTransport(
            lambda r: (
                html() if r.url.path == "/web/kas/sankcje" else httpx2.Response(404)
            )
        )
        async with safefetch.client(websearch.FETCH_TIMEOUT_S, transport) as client:
            return await websearch.fetch_document(
                "https://www.gov.pl/web/kas/sankcje", client
            )

    assert asyncio.run(go()) is not None
    assert saved == []


def test_slow_store_does_not_hold_up_web_search(monkeypatch):
    from tests.test_websearch import provider_returning, site

    monkeypatch.setattr(websearch, "SAVE_BUDGET_S", 0.05)
    monkeypatch.setattr(websearch, "save_document", lambda d: time.sleep(0.3))
    safefetch._robots.clear()

    async def go():
        started = time.monotonic()
        result = await websearch.search_web(
            "sankcje",
            provider=provider_returning("https://www.gov.pl/web/kas/sankcje"),
            transport=site({"www.gov.pl/web/kas/sankcje": html()}),
        )
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(go())
    assert len(result.documents) == 1
    assert elapsed < 0.3


def test_seed_is_the_only_database_writer(monkeypatch):
    from prawdowid import corpus

    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.setattr(corpus, "queries", lambda: ["sankcje"])
    monkeypatch.setattr(corpus, "ALLOWLIST", {"gov.pl": None})
    monkeypatch.setattr(
        corpus, "APPROVED_SOURCES", {"www.gov.pl": "Synthetic test licence"}
    )
    monkeypatch.setattr(corpus, "delete_expired", lambda: 0)
    monkeypatch.setattr(corpus, "stored_documents", list)
    stored, saves = [], []

    async def fake_search(query, *, domains, limit, save):
        saves.append(save)
        return websearch.WebSearch(documents=[doc()])

    monkeypatch.setattr(corpus, "search_web", fake_search)
    monkeypatch.setattr(corpus, "store_document", stored.append)
    asyncio.run(corpus.build(target=10))
    assert saves == [False]
    assert [d.url for d in stored] == [doc().url]


def test_seed_manifest_from_database_carries_no_page_text(monkeypatch, tmp_path):
    """Retention and deletion in the database must cover every copy of the text."""
    from prawdowid import corpus

    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(corpus, "stored_documents", lambda: [doc()])
    corpus.write_manifest()
    [row] = [
        json.loads(line)
        for line in Path("corpus/manifest.jsonl").read_text().splitlines()
    ]
    assert row["url"] == doc().url and "text" not in row
    assert sorted(p.name for p in Path("corpus").iterdir()) == ["manifest.jsonl"]


def test_local_database_url_uses_compose_settings(monkeypatch):
    from prawdowid.corpus import local_database_url

    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd")
    monkeypatch.setenv("DB_PORT", "6000")
    assert local_database_url() == (
        "postgresql://prawdowid:p%40ss%3Aw%2Frd@127.0.0.1:6000/prawdowid"
    )


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="needs a throwaway migrated Postgres in TEST_DATABASE_URL; the test WIPES it",
)
def test_long_document_does_not_crowd_out_others(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    _wipe(url)
    try:
        _check_long_document_does_not_crowd_out_others()
    finally:
        _wipe(url)  # no test fixtures left to show up in a later manifest


def _wipe(url):
    with psycopg.connect(url) as conn:
        conn.execute("truncate documents cascade")


def _check_long_document_does_not_crowd_out_others():
    long = doc("https://www.gov.pl/long")
    long.text = "\n\n".join(
        f"Sankcje wobec Rosji, akapit {i}. " * 20 for i in range(25)
    )
    short = doc("https://www.nato.int/short")
    short.text = "NATO komentuje sankcje."
    assert store_document(long) and store_document(short)

    result = asyncio.run(search_documents("sankcje", limit=5))
    assert [f.doc_id for f in result.fragments] == [
        "https://gov.pl/long",
        "https://nato.int/short",
    ]
    assert result.fragments[0].source.fragment.count("\n\n") < cache.CHUNKS_PER_DOCUMENT
