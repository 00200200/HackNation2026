"""Tavily query cache (#110): hit and miss, TTL, failures, limit errors, masking, persistence. Offline."""

import asyncio
import json
import time
from datetime import date

import httpx2
import pytest
from tavily import UsageLimitExceededError
from tavily.errors import BadRequestError, ForbiddenError

from prawdowid import search_cache, websearch
from prawdowid.websearch import SearchHit, SearchUnavailable

HIT = SearchHit(url="https://www.gov.pl/a", title="t", snippet="s")


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("PRAWDOWID_SEARCH_CACHE_PATH", str(tmp_path / "sc.jsonl"))
    monkeypatch.delenv("PRAWDOWID_SEARCH_CACHE_TTL_S", raising=False)
    monkeypatch.setattr(search_cache, "_cache", None)
    monkeypatch.setattr(search_cache, "_cache_ttl", -1.0)
    monkeypatch.setattr(search_cache, "_limit_until", 0.0)
    search_cache.STATS.clear()


@pytest.fixture
def tavily(monkeypatch):
    calls = []

    def fake(query, *, domains, limit):
        calls.append((query, tuple(domains), limit))
        return [HIT.model_copy(update={"published_date": date(2025, 3, 11)})]

    monkeypatch.setattr(websearch, "tavily_search", fake)
    return calls


def search(query="Ile kosztuje paszport", domains=("gov.pl",), limit=5):
    return search_cache.cached_tavily_search(query, domains=domains, limit=limit)


def test_second_identical_query_is_a_cache_hit(tavily):
    first, second = search(), search()
    assert len(tavily) == 1
    assert first == second
    assert second[0].published_date.isoformat() == "2025-03-11"
    assert search_cache.STATS["tavily_calls"] == 1
    assert search_cache.STATS["cache_hits"] == 1


def test_key_folds_case_and_whitespace_and_domain_order(tavily):
    search("Ile  kosztuje PASZPORT", domains=("gov.pl", "who.int"))
    search(" ile kosztuje paszport ", domains=("who.int", "gov.pl"))
    assert len(tavily) == 1


@pytest.mark.parametrize(
    "other",
    [{"query": "inne pytanie"}, {"limit": 3}, {"domains": ("gov.pl", "who.int")}],
)
def test_different_query_limit_or_domains_is_a_miss(tavily, other):
    search()
    search(**other)
    assert len(tavily) == 2


def test_ttl_expiry_calls_tavily_again(tavily, monkeypatch):
    now = [1000.0]
    monkeypatch.setenv("PRAWDOWID_SEARCH_CACHE_TTL_S", "60")
    monkeypatch.setattr(search_cache, "_cache_ttl", 60.0)
    monkeypatch.setattr(
        search_cache, "_cache", search_cache.SearchCache(60, clock=lambda: now[0])
    )
    search()
    now[0] += 59
    search()
    assert len(tavily) == 1
    now[0] += 2
    search()
    assert len(tavily) == 2


def test_ttl_zero_turns_the_cache_off(tavily, monkeypatch, tmp_path):
    monkeypatch.setenv("PRAWDOWID_SEARCH_CACHE_TTL_S", "0")
    search()
    search()
    assert len(tavily) == 2
    assert not (tmp_path / "sc.jsonl").exists()


def test_ttl_is_capped_by_retention(monkeypatch):
    monkeypatch.setenv("PRAWDOWID_SEARCH_CACHE_TTL_S", str(10**9))
    assert search_cache.ttl_s() == search_cache.RETENTION_DAYS * 86_400
    monkeypatch.setenv("PRAWDOWID_SEARCH_CACHE_TTL_S", "junk")
    assert search_cache.ttl_s() == search_cache.DEFAULT_TTL_S


def test_failures_are_not_cached(monkeypatch):
    calls = []

    def flaky(query, *, domains, limit):
        calls.append(query)
        if len(calls) == 1:
            raise SearchUnavailable("boom") from BadRequestError("bad")
        return [HIT]

    monkeypatch.setattr(websearch, "tavily_search", flaky)
    with pytest.raises(SearchUnavailable):
        search()
    assert search() == [HIT]
    assert len(calls) == 2
    assert search_cache.STATS["failures"] == 1
    assert not search_cache.is_limit(SearchUnavailable("boom"))


@pytest.mark.parametrize(
    "cause",
    [
        UsageLimitExceededError("Usage limit reached"),
        ForbiddenError("This request exceeds your plan's set usage limit."),
        ForbiddenError("This request exceeds the pay-as-you-go limit."),
    ],
)
def test_limit_errors_are_a_distinct_reason_and_not_cached(monkeypatch, cause):
    calls = []

    def limited(query, *, domains, limit):
        calls.append(query)
        raise SearchUnavailable(str(cause)) from cause

    monkeypatch.setattr(websearch, "tavily_search", limited)
    with pytest.raises(SearchUnavailable) as err:
        search()
    assert search_cache.is_limit(err.value)
    assert search_cache.STATS["limit_errors"] == 1
    # cool-down: the retry makes no call
    with pytest.raises(SearchUnavailable) as again:
        search()
    assert search_cache.is_limit(again.value)
    assert len(calls) == 1


def test_forbidden_without_limit_text_is_a_plain_failure(monkeypatch):
    cause = ForbiddenError("Forbidden")

    def denied(query, *, domains, limit):
        raise SearchUnavailable("Forbidden") from cause

    monkeypatch.setattr(websearch, "tavily_search", denied)
    with pytest.raises(SearchUnavailable) as err:
        search()
    assert not search_cache.is_limit(err.value)


def test_cache_survives_a_restart_and_stores_no_query(tavily, tmp_path, monkeypatch):
    search("Sekretne pytanie")
    text = (tmp_path / "sc.jsonl").read_text()
    assert "Sekretne" not in text
    assert set(json.loads(text)["hits"][0]) == {
        "url",
        "title",
        "snippet",
        "published_date",
    }
    monkeypatch.setattr(search_cache, "_cache", None)
    monkeypatch.setattr(search_cache, "_cache_ttl", -1.0)
    search("Sekretne pytanie")
    assert len(tavily) == 1


def test_expired_and_damaged_lines_leave_the_file_on_load(tmp_path):
    path = tmp_path / "old.jsonl"
    live = {
        "key": "k1",
        "stored_at": 990.0,
        "hits": [{"url": "u", "title": "", "snippet": ""}],
    }
    old = {**live, "key": "k2", "stored_at": 1.0}
    path.write_text(
        "\n".join([json.dumps(live), json.dumps(old), "{not json", '{"key": 1}'])
    )
    cache = search_cache.SearchCache(60, path, clock=lambda: 1000.0)
    assert cache.get("k1") and cache.get("k2") is None
    assert [json.loads(line)["key"] for line in path.read_text().splitlines()] == ["k1"]


def test_cache_is_bounded():
    cache = search_cache.SearchCache(60, maxsize=2)
    for key in "abc":
        cache.put(key, [])
    assert sum(cache.get(k) is not None for k in "abc") == 2


def test_check_counter_sees_calls_and_hits(tavily):
    with search_cache.track() as counts:
        search()
        search()
    assert counts == {"tavily_calls": 1, "cache_hits": 1}


def test_search_web_default_provider_is_cached_and_masks_the_query(tavily, monkeypatch):
    assert (
        websearch.search_web.__kwdefaults__["provider"]
        is search_cache.cached_tavily_search
    )
    query = "Co zrobił Jan na jan.kowalski@example.com"
    offline = httpx2.MockTransport(lambda request: httpx2.Response(404))
    for _ in range(2):
        asyncio.run(websearch.search_web(query, save=False, transport=offline))
    assert len(tavily) == 1
    assert "example.com" not in tavily[0][0]


@pytest.mark.parametrize(
    "hits",
    [["x"], "x", {"url": "u"}, [{"url": "u", "title": None, "snippet": "s"}]],
)
def test_a_damaged_line_is_skipped_not_fatal(tmp_path, hits):
    """A line that is JSON but not a valid record is dropped on load; search keeps working."""
    path = tmp_path / "s.jsonl"
    good = {
        "key": "k2",
        "stored_at": time.time(),
        "hits": [{"url": "u", "title": "t", "snippet": "s"}],
    }
    path.write_text(
        json.dumps({"key": "k", "stored_at": time.time(), "hits": hits})
        + "\n"
        + json.dumps(good)
        + "\n"
    )
    cache = search_cache.SearchCache(60, path)
    assert cache.get("k") is None
    assert [h["url"] for h in cache.get("k2")] == ["u"]


def test_expired_rows_leave_the_file_without_new_writes(tmp_path):
    """#110 retention: the file is swept on reads too, and kept rows keep their timestamps."""
    now = [1000.0]
    path = tmp_path / "age.jsonl"
    cache = search_cache.SearchCache(600, path, clock=lambda: now[0])
    cache.put("old", [])
    now[0] = 1500.0
    cache.put("new", [])
    now[0] = 1700.0  # "old" is 700 s old, "new" 200 s
    assert cache.get("new") is not None
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["key"], r["stored_at"]) for r in rows] == [("new", 1500.0)]


def test_a_cache_file_cut_inside_a_character_is_not_fatal(tmp_path):
    path = tmp_path / "cut.jsonl"
    good = {"key": "k", "stored_at": time.time(), "hits": []}
    path.write_bytes(
        (json.dumps(good) + "\n").encode()
        + '{"key": "z", "title": "Zażółć'.encode()[:-1]
    )
    cache = search_cache.SearchCache(60, path)
    assert cache.get("k") == []


@pytest.mark.parametrize("cooldown", [False, True])
def test_a_search_limit_has_its_own_message(monkeypatch, cooldown):
    cause = UsageLimitExceededError("Usage limit reached")

    def limited(query, *, domains, limit):
        raise SearchUnavailable(str(cause)) from cause

    monkeypatch.setattr(websearch, "tavily_search", limited)
    if cooldown:
        with pytest.raises(SearchUnavailable):
            search()
    result = asyncio.run(websearch.search_web("pytanie", save=False))
    assert result.failed and result.limitation == websearch.SEARCH_LIMIT
    assert "limit wyszukiwarki" in result.limitation
