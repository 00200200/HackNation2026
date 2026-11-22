import inspect

import pytest
from fastapi.testclient import TestClient

from corpus.catalog import load_catalog
from corpus.check import DOCS_PATH, summarize
from corpus.schema import MAX_TEXT_CHARS, read_jsonl
from prawdowid import euvsdisinfo, factcheck, govpl, pipeline, sources, websearch
from prawdowid.app import app


@pytest.fixture(scope="module")
def corpus_summary():
    return summarize(read_jsonl(DOCS_PATH))


def listing() -> dict:
    resp = TestClient(app).get("/api/sources")
    assert resp.status_code == 200
    return resp.json()


def test_corpus_numbers_are_the_ones_corpus_check_reports(corpus_summary):
    corpus = listing()["corpus"]
    assert corpus["records"] == corpus_summary["documents"]
    assert corpus["domains"] == len(corpus_summary["registered_domains"])
    assert corpus["strict_domains"] == len(corpus_summary["strict_domains"])
    assert corpus["source_types"] == corpus_summary["source_types"]
    assert corpus["without_published_at"] == corpus_summary["without_published_at"]
    assert corpus["in_checks"] is sources.CORPUS_IN_CHECKS


def test_every_catalogue_entry_is_listed_with_its_records(corpus_summary):
    entries = {e["id"]: e for e in listing()["catalogue"]}
    catalogue = load_catalog().sources
    assert list(entries) == [s.id for s in catalogue]
    for source in catalogue:
        entry = entries[source.id]
        assert entry["records"] == corpus_summary["sources"].get(source.id, 0)
        assert (entry["last_retrieved_at"] is None) == (entry["records"] == 0)
        if source.status == "excluded":
            assert entry["excluded_reason"] and entry["excluded_on"]


def test_full_text_shows_where_it_is_cut():
    entries = {e["id"]: e for e in listing()["catalogue"]}
    assert entries["odyseusz"]["max_chars"] == 8000
    assert entries["gus"]["max_chars"] == MAX_TEXT_CHARS
    assert entries["kgsok"]["max_chars"] is None  # a fragment, not full text


def test_last_retrieval_is_the_newest_record_of_the_source():
    docs = [d for d in read_jsonl(DOCS_PATH) if d.source_id == "odyseusz"]
    entry = next(e for e in listing()["catalogue"] if e["id"] == "odyseusz")
    assert entry["last_retrieved_at"] == max(d.retrieved_at for d in docs)


def test_unchecked_licences_are_not_shown_as_licences():
    """The catalogue writes "not checked" or "UNCONFIRMED"; the page says "do potwierdzenia"."""
    raw = {s.id: s.licence for s in load_catalog().sources}
    for entry in listing()["catalogue"]:
        unchecked = raw[entry["id"]].startswith(("not checked", "UNCONFIRMED"))
        assert (entry["licence"] is None) == unchecked
        assert entry["licence"] in (None, raw[entry["id"]])


def test_catalogue_says_which_domains_web_search_can_still_return():
    """An entry excluded from the corpus can still be on the web-search allowlist (Konkret24)."""
    entries = {e["id"]: e for e in listing()["catalogue"]}
    assert entries["konkret24"]["status"] == "excluded"
    assert entries["konkret24"]["in_web_search"] is True
    assert entries["edmo"]["in_web_search"] is False
    assert entries["utk"]["in_web_search"] is True  # under gov.pl


def test_web_search_lists_the_allowlist():
    domains = {d["domain"]: d for d in listing()["web_search"]}
    assert list(domains) == list(websearch.ALLOWLIST)
    for name, entry in websearch.ALLOWLIST.items():
        assert domains[name]["source_type"] == entry.source_type
        assert domains[name]["licence"] == entry.licence


def test_lookups_say_whether_they_run_in_this_deployment(monkeypatch):
    lookups = {lookup["id"]: lookup for lookup in listing()["lookups"]}
    assert set(lookups) == {"factcheck", "euvsdisinfo", "govpl", "web"}
    # conftest removes every key and switches gov.pl off.
    assert not any(lookup["active"] for lookup in lookups.values())

    for env in (factcheck.KEY_ENV, euvsdisinfo.KEY_ENV, websearch.KEY_ENV):
        monkeypatch.setenv(env, "test-key")
    monkeypatch.setattr(govpl, "ENABLED", True)
    assert all(lookup["active"] for lookup in listing()["lookups"])


def test_answer_never_carries_a_key(monkeypatch):
    monkeypatch.setenv(factcheck.KEY_ENV, "secret-value-123")
    assert "secret-value-123" not in TestClient(app).get("/api/sources").text


# Row id on /zrodla -> the module pipeline.py calls for that step 2 lookup.
LOOKUP_MODULES = {
    "factcheck": "prawdowid.factcheck",
    "euvsdisinfo": "prawdowid.euvsdisinfo",
    "govpl": "prawdowid.govpl",
    "web": "prawdowid.websearch",
}


def test_every_lookup_of_the_pipeline_has_a_row():
    """A lookup added to pipeline.py (a new register, a new API) must get a row on /zrodla."""
    called = {
        module.__name__
        for module in vars(pipeline).values()
        if inspect.ismodule(module) and module.__name__.startswith("prawdowid.")
    }
    # Steps 3 to 5, the corpus, which has its own flag (test below), and the eval-only fault switch,
    # which is no source.
    called -= {
        "prawdowid.judge",
        "prawdowid.rerank",
        "prawdowid.corpus_search",
        "prawdowid.corpus_bm25",
        "prawdowid.faults",
    }
    assert {lookup["id"] for lookup in listing()["lookups"]} == set(LOOKUP_MODULES)
    assert called == set(LOOKUP_MODULES.values())


def test_corpus_flag_follows_the_pipeline():
    """The page says whether a check searches the corpus; flip CORPUS_IN_CHECKS with #74."""
    assert sources.CORPUS_IN_CHECKS is ("search_corpus" in inspect.getsource(pipeline))
