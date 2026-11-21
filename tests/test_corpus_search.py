"""Corpus index and search. Unit tests run offline; the SQL tests need a Postgres with pgvector
and run only when TEST_DATABASE_URL is set (they create and drop their own tables)."""

import asyncio
import os
from datetime import UTC, datetime

import numpy as np
import psycopg
import pytest

from prawdowid import corpus_search, embeddings
from prawdowid.corpus_search import (
    SEARCH_UNAVAILABLE,
    search_corpus,
    to_hit,
    tsquery_terms,
)
from prawdowid.index import chunk_text, content_hash, load

TEST_DB = os.getenv("TEST_DATABASE_URL")
DIM = 8


def record(id_: str, title: str, text: str, **extra) -> dict:
    return {
        "id": id_,
        "url": f"https://example.gov.pl/{id_}",
        "title": title,
        "publisher": "Urząd Testowy",
        "published_at": "2026-11-19",
        "retrieved_at": "2026-11-21T15:00:00+00:00",
        "source_type": "official",
        "source_id": "test",
        "licence": "CC BY-SA 4.0",
        "language": "pl",
        "text": text,
        "storage": "full_text",
        "truncated": False,
        **extra,
    }


def fake_vector(text: str) -> np.ndarray:
    """Same words, same vector: enough to test the SQL without the real model."""
    vec = np.zeros(DIM, dtype=np.float32)
    for word in text.lower().split():
        vec[sum(map(ord, word.strip(".,:?!„”"))) % DIM] += 1
    return vec / (np.linalg.norm(vec) or 1)


# -- offline --------------------------------------------------------------------------------------


def test_chunks_are_verbatim_parts_and_respect_the_limit():
    text = "Tytuł\n" + " ".join(["słowo"] * 500) + "\nKoniec akapitu.\nDrugi akapit."
    chunks = chunk_text(text, limit=300)
    assert all(len(c) <= 300 for c in chunks)
    assert all(c in text for c in chunks)
    assert chunks[0] == "Tytuł" and chunks[1].startswith("słowo słowo")
    assert chunks[-1].endswith("Koniec akapitu.\nDrugi akapit.")
    assert chunk_text("krótki tekst") == ["krótki tekst"]
    assert chunk_text("a\n\nb") == ["a\n\nb"]
    assert all(c in "x\n\n\ny" for c in chunk_text("x\n\n\ny", limit=1))


def test_content_hash_follows_what_is_embedded():
    a = record("a", "T", "tekst")
    assert content_hash(a) == content_hash(
        {**a, "retrieved_at": "2026-11-22T08:00:00+00:00"}
    )
    assert content_hash(a) != content_hash({**a, "text": "inny tekst"})
    assert content_hash(a) != content_hash({**a, "title": "inny tytuł"})


def test_query_terms_are_prefixes_without_stopwords():
    assert (
        tsquery_terms("Czy we Włoszech odbył się strajk?")
        == "włoszech:* | odbył:* | strajk:*"
    )
    assert tsquery_terms("czy to?") == ""
    assert tsquery_terms("x'); DROP TABLE chunks; --") == "drop:* | table:* | chunks:*"


def test_row_becomes_a_source_with_the_chunk_as_fragment():
    row = (
        "Włochy – informacje dla podróżujących",
        "MSZ",
        datetime(2026, 11, 19, tzinfo=UTC),
        datetime(2026, 11, 21, 15, tzinfo=UTC),
        "https://odyseusz.gov.pl/api/v1/informacje/profile-panstw/IT",
        "official",
        None,
        None,
        "W dniu 20 listopada zapowiedziano strajk generalny.",
        0.032,
    )
    hit = to_hit(row)
    assert hit.source.published_at.isoformat() == "2026-11-19"
    assert hit.source.fragment == "W dniu 20 listopada zapowiedziano strajk generalny."
    assert hit.score == pytest.approx(0.032)


def test_search_without_a_database_is_a_limitation(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    found = asyncio.run(search_corpus("strajk"))
    assert (found.hits, found.limitation) == ([], SEARCH_UNAVAILABLE)


def test_unreachable_database_is_a_limitation_not_an_error(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setattr(embeddings, "is_ready", lambda: True)
    monkeypatch.setattr(embeddings, "embed_query", fake_vector)
    found = asyncio.run(search_corpus("strajk"))
    assert (found.hits, found.limitation) == ([], SEARCH_UNAVAILABLE)


def test_search_waits_for_the_model_instead_of_loading_it_inside_the_deadline(
    monkeypatch,
):
    started = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setattr(embeddings, "is_ready", lambda: False)
    monkeypatch.setattr(embeddings, "warm_up", lambda: started.append(True))
    found = asyncio.run(search_corpus("strajk"))
    assert (found.hits, found.limitation, started) == ([], SEARCH_UNAVAILABLE, [True])


def test_a_model_error_is_a_limitation(monkeypatch):
    def broken(_):
        raise ValueError("Could not load model")

    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setattr(embeddings, "is_ready", lambda: True)
    monkeypatch.setattr(embeddings, "embed_query", broken)
    assert asyncio.run(search_corpus("strajk")).limitation == SEARCH_UNAVAILABLE


def use_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setattr(embeddings, "is_ready", lambda: True)
    monkeypatch.setattr(embeddings, "embed_query", fake_vector)


# -- against Postgres ------------------------------------------------------------------------------

needs_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def db():
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute(
            "DROP TABLE IF EXISTS corpus_chunks, corpus_documents, corpus_meta"
        )
        yield conn
        conn.execute(
            "DROP TABLE IF EXISTS corpus_chunks, corpus_documents, corpus_meta"
        )


def index(conn, records, model="test-model"):
    return load(
        records,
        conn,
        embed=lambda texts: [fake_vector(t) for t in texts],
        model=model,
        dim=DIM,
    )


CORPUS = [
    record(
        "strajk",
        "Włochy – informacje dla podróżujących",
        "W dniu 20 listopada zapowiedziano strajk generalny.",
    ),
    record(
        "powodz",
        "Ostrzeżenie hydrologiczne",
        "Wezbranie z przekroczeniem stanu alarmowego na Odrze.",
    ),
    record(
        "demagog",
        "Darmowa komunikacja dla 65-latków",
        "Ocena: Fałsz. Wrocław nie był jedynym miastem z darmową komunikacją dla seniorów.",
        source_type="fact_checker",
        rating="Fałsz",
        claim="Wrocław był jedynym miastem z darmową komunikacją dla 65-latków.",
    ),
]


@needs_db
def test_load_is_incremental_and_follows_the_file(db):
    assert index(db, CORPUS) == {
        "documents": 3,
        "changed": 3,
        "removed": 0,
        "chunks": 3,
    }
    assert index(db, CORPUS)["changed"] == 0
    edited = [CORPUS[0], {**CORPUS[1], "text": "Nowa treść ostrzeżenia."}]
    assert index(db, edited) == {
        "documents": 2,
        "changed": 1,
        "removed": 1,
        "chunks": 1,
    }
    assert db.execute("SELECT count(*) FROM corpus_chunks").fetchone()[0] == 2
    refetched = [
        {**CORPUS[0], "retrieved_at": "2026-11-22T08:00:00+00:00", "rating": "Prawda"}
    ]
    assert index(db, refetched)["chunks"] == 0  # same text: no new embeddings
    assert db.execute("SELECT rating FROM corpus_documents").fetchone()[0] == "Prawda"


@needs_db
def test_another_model_rebuilds_the_index(db):
    index(db, CORPUS)
    assert index(db, CORPUS, model="other-model")["changed"] == 3


@needs_db
def test_hybrid_search_finds_the_document_and_keeps_its_metadata(db, monkeypatch):
    index(db, CORPUS)
    use_db(monkeypatch)
    found = asyncio.run(search_corpus("strajk generalny we Włoszech", k=3))
    assert found.limitation is None
    top = found.hits[0]
    assert top.source.url.path == "/strajk"
    assert top.source.fragment == "W dniu 20 listopada zapowiedziano strajk generalny."
    assert top.source.published_at.isoformat() == "2026-11-19"
    fact = asyncio.run(
        search_corpus("Wrocław darmowa komunikacja 65-latków", k=1)
    ).hits[0]
    assert (fact.rating, fact.source.source_type) == ("Fałsz", "fact_checker")
    assert fact.reviewed_claim.startswith("Wrocław był jedynym miastem")


@needs_db
def test_at_most_two_chunks_per_document(db, monkeypatch):
    long_text = "\n".join(
        f"Strajk generalny akapit {n} " + "x " * 500 for n in range(5)
    )
    index(db, [record("dlugi", "Strajk", long_text)])
    use_db(monkeypatch)
    found = asyncio.run(search_corpus("strajk generalny", k=10))
    assert len(found.hits) == corpus_search.PER_DOC


@needs_db
def test_search_says_when_the_index_is_being_rebuilt(db, monkeypatch):
    index(db, CORPUS)
    use_db(monkeypatch)
    assert asyncio.run(search_corpus("strajk")).limitation is None
    db.execute("UPDATE corpus_meta SET value = 'false' WHERE key = 'complete'")
    found = asyncio.run(search_corpus("strajk"))
    assert found.hits and found.limitation == corpus_search.INDEX_INCOMPLETE


@needs_db
def test_search_before_the_first_load_is_a_limitation(db, monkeypatch):
    use_db(monkeypatch)
    assert asyncio.run(search_corpus("strajk")).limitation == SEARCH_UNAVAILABLE
