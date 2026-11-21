import asyncio
import time
from datetime import date
from pathlib import Path

import httpx2
import pytest
import requests
from tavily import BadRequestError, InvalidAPIKeyError, UsageLimitExceededError
from tavily.errors import ForbiddenError
from tavily.errors import TimeoutError as TavilyTimeoutError

from prawdowid import cache, websearch
from prawdowid.privacy import mask_personal_data
from prawdowid.websearch import (
    ALLOWLIST,
    NOTHING_FETCHED,
    SEARCH_UNAVAILABLE,
    SearchHit,
    SearchUnavailable,
    allowed,
    search_web,
)

PAGE = """<html><head><title>Sankcje wobec Rosji</title>
<meta property="article:published_time" content="2025-06-02T10:00:00Z"></head>
<body><article><h1>Sankcje wobec Rosji</h1>
<p>Rada UE przyjęła kolejny pakiet sankcji wobec Rosji. Obejmuje on zakaz importu
gazu skroplonego i dodatkowe osoby na liście sankcyjnej.</p>
<p>Pakiet wchodzi w życie z dniem publikacji w Dzienniku Urzędowym UE.</p>
</article></body></html>"""
UNDATED = PAGE.replace(
    '<meta property="article:published_time" content="2025-06-02T10:00:00Z">', ""
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(
        websearch,
        "save_document",
        lambda d: cache.save_document(d, tmp_path / "docs.jsonl"),
    )
    websearch._robots.clear()
    return tmp_path / "docs.jsonl"


def provider_returning(*urls, calls=None):
    def provider(query, *, domains, limit):
        if calls is not None:
            calls.append(query)
        return [SearchHit(url=u, title="t", snippet="s") for u in urls]

    return provider


def provider_returning_with_dates(*url_dates):
    def provider(query, *, domains, limit):
        return [
            SearchHit(url=u, title="t", snippet="s", published_date=d)
            for u, d in url_dates
        ]

    return provider


def site(routes, seen=None):
    """MockTransport: host+path -> response; anything else (robots.txt too) is a 404."""

    def handler(request):
        if seen is not None:
            seen.append(str(request.url))
        key = f"{request.url.host}{request.url.path}"
        if key in routes:
            return routes[key]
        return httpx2.Response(404)

    return httpx2.MockTransport(handler)


def html(body=PAGE):
    return httpx2.Response(
        200, text=body, headers={"content-type": "text/html; charset=utf-8"}
    )


def run(provider, routes, seen=None, **kwargs):
    async def go():
        return await search_web(
            "sankcje", provider=provider, transport=site(routes, seen), **kwargs
        )

    return asyncio.run(go())


def test_personal_data_is_masked_but_amounts_are_kept():
    text = (
        "Pisz na jan.kowalski@example.com, tel. +48 600 100 200 lub 600-100-200, "
        "PESEL 44051401359, konto PL61 1090 1014 0000 0712 1981 2874. "
        "Rząd wydał 500 000 000 zł, czyli 100000000 euro, w 2024; rejestr 12345678901."
    )
    masked = mask_personal_data(text)
    assert "example.com" not in masked and "600" not in masked
    assert "44051401359" not in masked and "1090" not in masked
    # Amounts, years and 11 digits without a valid PESEL checksum stay.
    assert (
        "500 000 000 zł, czyli 100000000 euro, w 2024; rejestr 12345678901." in masked
    )


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.gov.pl/web/kas/sankcje", "gov.pl"),
        ("https://www.nik.gov.pl/aktualnosci", "gov.pl"),
        ("https://www.sejm.gov.pl/x", "sejm.gov.pl"),
        ("https://eur-lex.europa.eu/x", "eur-lex.europa.eu"),
        ("https://notgov.pl/x", None),
        ("https://gov.pl.evil.com/x", None),
        ("ftp://gov.pl/x", None),
        ("https://[www.gov.pl/x", None),
    ],
)
def test_allowlist_matches_host_or_closest_parent(url, domain):
    assert allowed(url) == (ALLOWLIST[domain] if domain else None)


def test_hits_are_fetched_extracted_and_cached(isolated):
    calls = []
    provider = provider_returning(
        "https://www.gov.pl/web/kas/sankcje",
        "https://www.gov.pl/web/kas/sankcje",  # duplicate hit
        "https://example.com/not-allowlisted",
        calls=calls,
    )
    result = run(provider, {"www.gov.pl/web/kas/sankcje": html()})

    assert result.limitation is None
    [doc] = result.documents
    assert doc.title == "Sankcje wobec Rosji"
    assert doc.published_at == date(2025, 6, 2)
    assert doc.source_type == "official"
    assert "gazu skroplonego" in doc.text
    source = doc.to_source()
    assert source.title and source.publisher and source.published_at and source.url
    assert [d.url for d in cache.load_documents(isolated)] == [doc.url]
    assert calls == ["sankcje"]


def test_query_is_masked_before_it_leaves():
    calls = []

    async def go():
        return await search_web(
            "Napisz do jan@example.com o sankcjach",
            provider=provider_returning(calls=calls),
        )

    asyncio.run(go())
    assert calls == ["Napisz do [e-mail] o sankcjach"]


def test_failed_search_is_retried_once_then_a_limitation():
    calls = []

    def failing(query, *, domains, limit):
        calls.append(query)
        raise SearchUnavailable("No results found.")

    result = run(failing, {})
    assert result.limitation == SEARCH_UNAVAILABLE
    assert result.documents == []
    assert len(calls) == 2


def test_no_allowlisted_hit_is_a_limitation():
    result = run(provider_returning("https://example.com/x"), {})
    assert result.limitation == SEARCH_UNAVAILABLE


@pytest.mark.parametrize(
    "routes",
    [
        {"www.gov.pl/p": httpx2.Response(403)},
        {
            "www.gov.pl/p": httpx2.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            )
        },
        {"www.gov.pl/p": html(UNDATED)},  # no publication date
        {
            "www.gov.pl/p": html(),
            "www.gov.pl/robots.txt": httpx2.Response(
                200, text="User-agent: *\nDisallow: /"
            ),
        },
        {
            "www.gov.pl/p": httpx2.Response(
                302, headers={"location": "https://example.com/p"}
            ),
            "example.com/p": html(),
        },
    ],
    ids=["blocked", "not-html", "undated", "robots", "redirect-off-allowlist"],
)
def test_unusable_pages_are_skipped(routes, isolated):
    result = run(provider_returning("https://www.gov.pl/p"), routes)
    assert result.documents == []
    assert result.limitation == NOTHING_FETCHED
    assert not isolated.exists()


def test_cache_keeps_one_document_per_url(tmp_path):
    result = run(
        provider_returning("https://www.gov.pl/p"), {"www.gov.pl/p": html()}, save=False
    )
    [doc] = result.documents
    path = tmp_path / "c.jsonl"
    assert cache.save_document(doc, path) is True
    assert cache.save_document(doc, path) is False
    assert cache.load_documents(path) == [doc]


@pytest.mark.parametrize(
    "exc",
    [
        InvalidAPIKeyError("Unauthorized"),
        BadRequestError("Bad request"),
        ForbiddenError("Forbidden"),
        UsageLimitExceededError("Usage limit exceeded"),
        TavilyTimeoutError(timeout=10),
        requests.ConnectionError("down"),
        requests.HTTPError("502"),
    ],
    ids=[
        "invalid-key",
        "bad-request",
        "forbidden",
        "usage-limit",
        "tavily-timeout",
        "connection-error",
        "http-error",
    ],
)
def test_tavily_errors_become_search_unavailable(monkeypatch, exc):
    class Broken:
        def search(self, *args, **kwargs):
            raise exc

    monkeypatch.setattr(websearch, "_client", Broken())
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    with pytest.raises(SearchUnavailable):
        websearch.tavily_search("x", domains=["gov.pl"], limit=5)


def test_tavily_without_a_key_is_search_unavailable(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(SearchUnavailable):
        websearch.tavily_search("x", domains=["gov.pl"], limit=5)


def test_tavily_hit_is_mapped_to_a_search_hit(monkeypatch):
    class Fake:
        def search(self, query, **kwargs):
            assert kwargs["include_domains"] == ["gov.pl"]
            assert kwargs["include_domains_mode"] == "restrict"
            return {
                "results": [
                    {
                        "url": "https://www.gov.pl/p",
                        "title": "t",
                        "content": "c",
                        "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
                    },
                    {"url": "", "title": "no url, skipped"},
                ]
            }

    monkeypatch.setattr(websearch, "_client", Fake())
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    hits = websearch.tavily_search("x", domains=["gov.pl"], limit=5)
    assert [h.url for h in hits] == ["https://www.gov.pl/p"]
    assert hits[0].published_date == date(2025, 3, 11)


def test_tavily_date_accepts_iso_and_rfc2822():
    assert websearch._tavily_date("2025-02-09") == date(2025, 2, 9)
    assert websearch._tavily_date("Tue, 11 Mar 2025 17:00:00 GMT") == date(2025, 3, 11)
    assert websearch._tavily_date(None) is None
    assert websearch._tavily_date("garbage") is None


def test_search_hit_date_fills_in_a_page_without_one(isolated):
    provider = provider_returning_with_dates(("https://www.gov.pl/p", date(2025, 1, 1)))
    result = run(provider, {"www.gov.pl/p": html(UNDATED)})
    assert result.limitation is None
    [doc] = result.documents
    assert doc.published_at == date(2025, 1, 1)


def test_source_list_documents_every_allowlisted_domain():
    sources = Path("docs/sources.md").read_text(encoding="utf-8")
    assert [d for d in ALLOWLIST if f"`{d}`" not in sources] == []


def test_redirect_hop_off_the_allowlist_is_never_requested():
    seen = []
    routes = {
        "www.gov.pl/p": httpx2.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )
    }
    result = run(provider_returning("https://www.gov.pl/p"), routes, seen=seen)
    assert result.documents == []
    assert not [u for u in seen if "169.254" in u]


def test_malformed_hit_url_is_skipped_not_raised():
    result = run(
        provider_returning("https://www.gov.pl:99999/x", "https://www.gov.pl/p"),
        {"www.gov.pl/p": html()},
    )
    assert [d.url for d in result.documents] == ["https://www.gov.pl/p"]


def test_slow_page_is_cut_off(monkeypatch):
    async def slow(request):
        if request.url.path == "/robots.txt":
            return httpx2.Response(404)
        await asyncio.sleep(1)
        return html()

    monkeypatch.setattr(websearch, "PAGE_BUDGET_S", 0.05)

    async def go():
        return await search_web(
            "sankcje",
            provider=provider_returning("https://www.gov.pl/p"),
            transport=httpx2.MockTransport(slow),
        )

    assert asyncio.run(go()).limitation == NOTHING_FETCHED


def test_a_hanging_provider_is_cut_by_the_search_budget(monkeypatch):
    monkeypatch.setattr(websearch, "SEARCH_BUDGET_S", 0.2)

    def hanging(query, *, domains, limit):
        time.sleep(1)
        return []

    async def go():
        started = time.perf_counter()
        result = await websearch.search_web("sankcje", provider=hanging)
        return result, time.perf_counter() - started

    # asyncio.run then waits for the thread to end; the search itself does not.
    result, elapsed = asyncio.run(go())
    assert elapsed < 0.8
    assert result.limitation == websearch.SEARCH_UNAVAILABLE
