import asyncio
from datetime import datetime

import pytest
from fastmcp import FastMCP

from prawdowid import euvsdisinfo
from prawdowid.euvsdisinfo import KEY_ENV, LOOKUP_UNAVAILABLE, search_cases

# Shape of the documented `search` result: type, title, content, link.
RESULTS = [
    {
        "type": "claim_review",
        "title": "Poland plans to annex western Ukraine",
        "content": "Recurring pro-Kremlin disinformation narrative about Poland...",
        "link": "https://euvsdisinfo.eu/report/poland-plans-to-annex-western-ukraine/",
    },
    {
        "type": "article",
        "title": "Disinfo Review",
        "content": "x" * 2000,
        "link": "https://euvsdisinfo.eu/disinfo-review/",
    },
    {"type": "claim_review", "title": "No link"},
    {"type": "claim_review", "title": "Elsewhere", "link": "https://example.com/a"},
    {"type": "unknown", "title": "Other", "link": "https://euvsdisinfo.eu/x/"},
]


def fake_server(search):
    server = FastMCP("fake-euvsdisinfo")
    server.tool(search, name="search")
    return server


def run(server, query="Polska chce zaanektować zachodnią Ukrainę"):
    return asyncio.run(search_cases(query, server=server))


def test_known_case_returns_a_source_with_its_link():
    queries = []

    def search(
        query: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        queries.append(query)
        return RESULTS

    lookup = run(fake_server(search))

    assert lookup.limitation is None
    assert queries == ["Polska chce zaanektować zachodnią Ukrainę"]
    case, article = lookup.hits  # no link, foreign link and unknown type are dropped
    assert case.kind == "claim_review"
    assert case.source.title == "Poland plans to annex western Ukraine"
    assert str(case.source.url) == RESULTS[0]["link"]
    assert case.source.publisher == "EUvsDisinfo (ESDZ)"
    assert case.source.source_type == "disinfo_database"
    assert case.source.published_at is None  # `search` gives no date; never guessed
    assert isinstance(case.source.fetched_at, datetime)
    assert article.kind == "article"
    assert len(article.source.fragment) == euvsdisinfo.MAX_FRAGMENT_CHARS


def test_no_key_reports_the_source_unavailable(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)

    lookup = asyncio.run(search_cases("Polska chce zaanektować zachodnią Ukrainę"))

    assert lookup.hits == []
    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_server_error_is_retried_once_then_a_limitation():
    calls = []

    def search(query: str) -> list[dict]:
        calls.append(query)
        raise RuntimeError("Elasticsearch down")

    lookup = run(fake_server(search))

    assert len(calls) == euvsdisinfo.ATTEMPTS == 2
    assert lookup.hits == []
    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_retry_recovers_after_one_failure():
    calls = []

    def search(query: str) -> list[dict]:
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return RESULTS[:1]

    lookup = run(fake_server(search))

    assert len(lookup.hits) == 1 and lookup.limitation is None


def test_slow_server_hits_the_deadline(monkeypatch):
    monkeypatch.setattr(euvsdisinfo, "DEADLINE_S", 0.2)

    async def search(query: str) -> list[dict]:
        await asyncio.sleep(5)
        return RESULTS

    lookup = run(fake_server(search))

    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_single_hit_unwrapped_by_the_client_still_counts():
    def search(query: str) -> dict:
        return RESULTS[0]

    assert len(run(fake_server(search)).hits) == 1


@pytest.mark.parametrize("reply", ["not a list", {"error": "boom"}])
def test_unexpected_shape_is_a_limitation(reply):
    def search(query: str) -> str | dict:
        return reply

    assert run(fake_server(search)).limitation == LOOKUP_UNAVAILABLE


@pytest.mark.parametrize("query", ["", "  ab "])
def test_too_short_query_is_not_sent(query):
    def search(query: str) -> list[dict]:
        raise AssertionError("must not be called")

    lookup = run(fake_server(search), query)

    assert lookup.hits == [] and lookup.limitation is None
