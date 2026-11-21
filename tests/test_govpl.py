"""gov.pl site search, offline: recorded JSON answer and pages through a MockTransport."""

import asyncio
from datetime import date

import httpx2
import pytest

from prawdowid import govpl, safefetch, websearch

# Shape recorded from GET https://www.gov.pl/api/data/search on 2026-11-21, trimmed.
ANSWER = {
    "count": 10992,
    "results": [
        {
            "title": "Alert RCB - ćwiczenia systemów alarmowania (21.09)",
            "intro": "Ćwiczenia systemu alarmowania - Alert RCB w powiecie janowskim.",
            "publishDate": "2026-09-21T11:13:25.286645Z",
            "url": "/web/rcb/alert-rcb-2109",
            "path": "rcb",
        },
        {
            "title": "Komunikat",
            "intro": None,
            "publishDate": "2025-01-10T08:00:00Z",
            "url": "/web/nieznany-urzad/komunikat",
            "path": "nieznany-urzad",
        },
        {"title": "Bez adresu", "url": None, "path": "rcb"},
        {"title": "Inna strona", "url": "https://evil.example/x", "path": "rcb"},
    ],
    "hasMoreResults": True,
}
PAGE = """<html><head><title>{title} - Portal Gov.pl</title>
<meta property="og:site_name" content="{site}"></head>
<body><article><h1>{title}</h1>
<p>Rządowe Centrum Bezpieczeństwa przesłało Alert RCB do mieszkańców powiatu janowskiego
w ramach zaplanowanych ćwiczeń systemu alarmowania ludności.</p>
<p>Komunikat nie dotyczy rzeczywistego zagrożenia.</p></article></body></html>"""


def page(title: str, site: str = "Gov.pl") -> httpx2.Response:
    return httpx2.Response(
        200,
        text=PAGE.format(title=title, site=site),
        headers={"content-type": "text/html; charset=utf-8"},
    )


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(govpl, "ENABLED", True)
    govpl._searches.clear()
    safefetch._robots.clear()


def transport(answer=ANSWER, calls=None, search_status=200):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/api/data/search":
            if search_status != 200:
                return httpx2.Response(search_status)
            return httpx2.Response(200, json=answer)
        if request.url.path == "/web/rcb/alert-rcb-2109":
            return page("Alert RCB")
        if request.url.path == "/web/nieznany-urzad/komunikat":
            return page("Komunikat", "Urząd Testowy")
        return httpx2.Response(404)

    return httpx2.MockTransport(handler)


def run(queries, t):
    return asyncio.run(govpl.search_govpl(queries, transport=t))


def test_hits_become_official_documents_with_unit_and_search_date():
    calls = []
    result = run(["alert RCB"], transport(calls=calls))
    assert result.limitation is None
    rcb, other = result.documents
    assert rcb.url == "https://www.gov.pl/web/rcb/alert-rcb-2109"
    assert rcb.publisher == "Rządowe Centrum Bezpieczeństwa"
    assert rcb.published_at == date(2026, 9, 21)
    assert rcb.title == "Alert RCB - ćwiczenia systemów alarmowania (21.09)"
    assert rcb.source_type == "official"
    assert "przesłało Alert RCB do mieszkańców" in rcb.text  # verbatim page text
    # An unknown unit keeps the site name the page gives itself.
    assert other.publisher == "Urząd Testowy"
    search = next(c for c in calls if "/api/data/search" in c)
    assert "size=5" in search and "query=alert+RCB" in search
    # Hits without a /web/ path are never fetched.
    assert not any("evil.example" in c for c in calls)


def test_search_is_cached_per_query():
    calls = []
    run(["alert RCB"], transport(calls=calls))
    run(["alert RCB"], transport(calls=calls))
    assert sum("/api/data/search" in c for c in calls) == 1


def test_search_cache_expires(monkeypatch):
    calls = []
    run(["alert RCB"], transport(calls=calls))
    monkeypatch.setattr(govpl, "CACHE_TTL_S", 0)
    run(["alert RCB"], transport(calls=calls))
    assert sum("/api/data/search" in c for c in calls) == 2


def test_empty_answer_is_not_cached():
    calls = []
    empty = {"count": 0, "results": []}
    run(["alert RCB"], transport(answer=empty, calls=calls))
    run(["alert RCB"], transport(answer=empty, calls=calls))
    assert sum("/api/data/search" in c for c in calls) == 2


def test_at_most_two_queries_and_no_blank_ones():
    calls = []
    run(["  ", "a", "b", "c"], transport(calls=calls))
    searches = [c for c in calls if "/api/data/search" in c]
    assert len(searches) == 2 and not any("query=&" in c for c in searches)
    assert run([" "], transport()).limitation is None


def test_pages_are_capped_and_deduplicated_across_queries(monkeypatch):
    monkeypatch.setattr(govpl, "MAX_PAGES", 1)
    calls = []
    result = run(["alert RCB", "RCB ćwiczenia"], transport(calls=calls))
    assert [d.url for d in result.documents] == [
        "https://www.gov.pl/web/rcb/alert-rcb-2109"
    ]
    assert sum("/web/" in c for c in calls) == 1


@pytest.mark.parametrize("status", [403, 429, 500])
def test_refused_or_failing_search_is_a_limitation(status):
    calls = []
    result = run(["alert RCB"], transport(calls=calls, search_status=status))
    assert result.documents == []
    assert result.limitation == govpl.LOOKUP_UNAVAILABLE
    # One retry on a server error only; a block or rate limit is never retried.
    assert sum("/api/data/search" in c for c in calls) == (2 if status == 500 else 1)


def test_unusable_answer_is_a_limitation():
    result = run(["alert RCB"], transport(answer={"message": "x"}))
    assert result.limitation == govpl.LOOKUP_UNAVAILABLE


def test_no_hits_is_an_answer_not_a_failure():
    result = run(["alert RCB"], transport(answer={"count": 0, "results": []}))
    assert result.documents == [] and result.limitation is None


def test_slow_search_is_cut_by_its_budget(monkeypatch):
    monkeypatch.setattr(govpl, "SEARCH_BUDGET_S", 0.05)

    async def slow(request):
        await asyncio.sleep(5)
        return httpx2.Response(200, json=ANSWER)

    result = run(["alert RCB"], httpx2.MockTransport(slow))
    assert result.limitation == govpl.LOOKUP_UNAVAILABLE


def test_web_search_leaves_www_gov_pl_to_the_govpl_lookup(monkeypatch):
    monkeypatch.setattr(websearch, "save_document", lambda d: None)
    urls = ["https://www.gov.pl/web/rcb/a", "https://www.sejm.gov.pl/a"]

    limits = []

    def provider(query, *, domains, limit):
        limits.append(limit)
        return [websearch.SearchHit(url=u, title="t", snippet="s") for u in urls]

    fetched = []

    def handler(request):
        fetched.append(request.url.host)
        return httpx2.Response(404)

    asyncio.run(
        websearch.search_web(
            "q",
            provider=provider,
            transport=httpx2.MockTransport(handler),
            skip_hosts=govpl.HOSTS,
        )
    )
    assert "www.sejm.gov.pl" in fetched and "www.gov.pl" not in fetched
    assert limits == [10]  # skipped hosts take slots: twice the default 5
    only_gov = asyncio.run(
        websearch.search_web(
            "q",
            provider=lambda q, **k: provider(q, **k)[:1],
            transport=httpx2.MockTransport(handler),
            skip_hosts=govpl.HOSTS,
        )
    )
    assert only_gov.documents == [] and only_gov.limitation is None
