import asyncio
import sys

import psycopg
import pytest

from prawdowid import cache, corpus, websearch
from tests.test_cache import doc


def test_every_seed_host_passes_the_allowlist(tmp_path):
    # A seed outside the allowlist would only waste searches: every hit gets filtered out.
    assert all(websearch.allowed(f"https://{h}/") for h in corpus.search_domains())
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("gov.pl/no-scheme\nhttps://www.cert.pl/x\n")
    assert corpus.search_domains(seeds).count("cert.pl") == 1


@pytest.mark.parametrize(
    "approved", [{}, {"www.gov.pl": ""}, {"www.gov.pl": "UNCONFIRMED"}]
)
def test_database_seed_refuses_without_approved_sources(monkeypatch, approved):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.setattr(corpus, "APPROVED_SOURCES", approved, raising=False)
    monkeypatch.setattr(corpus, "queries", lambda: ["sankcje"])

    def unexpected(*args, **kwargs):
        pytest.fail("unapproved seed must refuse before database or network access")

    monkeypatch.setattr(corpus, "stored_documents", unexpected)
    monkeypatch.setattr(corpus, "delete_expired", unexpected)
    monkeypatch.setattr(corpus, "search_web", unexpected)
    with pytest.raises(SystemExit, match="no approved sources.*docs/sources.md"):
        asyncio.run(corpus.build(10))


def test_seed_stores_only_approved_final_hosts_with_confirmed_licence(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    monkeypatch.setattr(
        corpus,
        "APPROVED_SOURCES",
        {"www.gov.pl": "Synthetic test licence"},
        raising=False,
    )
    monkeypatch.setattr(corpus, "ALLOWLIST", {"www.gov.pl": None, "pap.pl": None})
    monkeypatch.setattr(corpus, "queries", lambda: ["sankcje"])
    monkeypatch.setattr(corpus, "stored_documents", list)
    monkeypatch.setattr(corpus, "delete_expired", lambda: 0)
    stored = []

    async def search(query, *, domains, limit, save):
        assert domains == ["www.gov.pl"] and save is False
        return websearch.WebSearch(
            documents=[
                doc(),
                doc("https://pap.pl/page"),
                doc("https://www.gov.pl.evil.test/page"),
            ]
        )

    monkeypatch.setattr(corpus, "search_web", search)
    monkeypatch.setattr(corpus, "store_document", stored.append)
    asyncio.run(corpus.build(10))
    assert [(d.url, d.licence) for d in stored] == [
        (doc().url, "Synthetic test licence")
    ]


def test_database_diagnostics_never_include_connection_error_text(monkeypatch, caplog):
    secret = "synthetic-password%bad"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{secret}@127.0.0.1:1/db")

    def fail(*args, **kwargs):
        raise psycopg.OperationalError(f"bad connection: {secret}")

    monkeypatch.setattr(psycopg, "connect", fail)
    result = asyncio.run(cache.search_documents("sankcje"))
    assert result.limitation == cache.DATABASE_UNAVAILABLE
    assert cache.store_document(doc()) is False
    assert "OperationalError" in caplog.text
    assert secret not in caplog.text


def test_seed_startup_reports_error_type_without_credentials(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:synthetic-password%bad@127.0.0.1:1/db"
    )
    monkeypatch.setattr(
        corpus,
        "APPROVED_SOURCES",
        {"www.gov.pl": "Synthetic test licence"},
        raising=False,
    )
    monkeypatch.setattr(sys, "argv", ["corpus", "--local-db"])

    def fail():
        raise psycopg.OperationalError("synthetic-password%bad")

    monkeypatch.setattr(corpus, "delete_expired", fail)
    assert corpus.main() == 1
    stderr = capsys.readouterr().err
    assert "OperationalError" in stderr
    assert "synthetic-password" not in stderr
    assert "Traceback" not in stderr
