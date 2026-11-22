import asyncio
import io
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpcore2
import httpx2
import pytest
import requests
from tavily import BadRequestError, InvalidAPIKeyError, UsageLimitExceededError
from tavily.errors import ForbiddenError
from tavily.errors import TimeoutError as TavilyTimeoutError

from prawdowid import cache, factcheck, safefetch, websearch
from prawdowid.privacy import mask_personal_data
from prawdowid.websearch import (
    ALLOWLIST,
    BLOCKED,
    NO_ANSWER,
    NOTHING_FETCHED,
    SEARCH_UNAVAILABLE,
    TOO_BIG,
    TOO_SLOW,
    UNREADABLE,
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
    safefetch._robots.clear()
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
        "PESEL 44051401359, PESEL:44051401359, PESEL44051401359, konto PL61 1090 1014 0000 0712 1981 2874. "
        "Rząd wydał 500 000 000 zł, czyli 100000000 euro, w 2024; rejestr 12345678901."
    )
    masked = mask_personal_data(text)
    assert "example.com" not in masked and "600" not in masked
    assert "44051401359" not in masked and "1090" not in masked
    assert masked.count("[PESEL]") == 3
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
    # Licence UNCONFIRMED: the cache keeps metadata, not the page text.
    [stored] = cache.load_documents(isolated)
    assert stored.url == doc.url and stored.title == doc.title and stored.text == ""
    assert calls == ["sankcje"]


def test_a_failed_cache_write_keeps_the_fetched_pages(monkeypatch):
    def unwritable(doc):
        raise PermissionError("read-only")

    monkeypatch.setattr(websearch, "save_document", unwritable)
    provider = provider_returning("https://www.gov.pl/web/kas/sankcje")
    result = run(provider, {"www.gov.pl/web/kas/sankcje": html()})
    assert result.limitation is None and len(result.documents) == 1


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


def test_no_allowlisted_hit_is_found_nothing_not_a_failure():
    result = run(provider_returning("https://example.com/x"), {})
    assert result.limitation is None and not result.failed and not result.documents


def typed(content: bytes, ctype: str):
    return httpx2.Response(200, content=content, headers={"content-type": ctype})


def pdf(text: str, title: str | None = None) -> bytes:
    """A one-page PDF drawing `text` (ASCII) with a standard font; `title` in its metadata."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 10 700 Td ({text}) Tj ET".encode())
    page = writer.add_blank_page(612, 792)
    page[NameObject("/Contents")] = writer._add_object(content)
    font = {
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): DictionaryObject(font)}
            )
        }
    )
    if title:
        writer.add_metadata({"/Title": title})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("routes", "reason"),
    [
        ({"www.gov.pl/p": httpx2.Response(403)}, BLOCKED),
        ({"www.gov.pl/p": httpx2.Response(429)}, BLOCKED),
        ({"www.gov.pl/p": httpx2.Response(503)}, NO_ANSWER),
        ({"www.gov.pl/p": httpx2.Response(302)}, UNREADABLE),  # no Location
        ({"www.gov.pl/p": typed(b"GIF89a", "image/gif")}, UNREADABLE),
        ({"www.gov.pl/p": typed(b"%PDF-1.7\n garbage", "application/pdf")}, UNREADABLE),
        ({"www.gov.pl/p": html("<html><body></body></html>")}, UNREADABLE),
        (
            {"www.gov.pl/p": httpx2.Response(302, headers={"location": "/p"})},
            UNREADABLE,
        ),
        (
            {
                "www.gov.pl/p": httpx2.Response(
                    302, headers={"location": "https://www.gov.pl:8443/p"}
                )
            },
            UNREADABLE,
        ),
    ],
    ids=[
        "403",
        "429",
        "5xx",
        "redirect-without-location",
        "image",
        "broken-pdf",
        "no-text",
        "redirect-loop",
        "other-port",
    ],
)
def test_a_page_we_cannot_read_stands_as_its_search_snippet(routes, reason, isolated):
    provider = provider_returning_with_dates(
        ("https://www.gov.pl/p", date(2026, 11, 3))
    )
    result = run(provider, routes)
    [doc] = result.documents
    assert doc.snippet_only == reason
    # Only what the search provider returned; type and publisher from the allowlist.
    assert (doc.url, doc.title, doc.text) == ("https://www.gov.pl/p", "t", "s")
    assert doc.published_at == date(2026, 11, 3)
    assert (doc.source_type, doc.publisher) == ("official", "www.gov.pl")
    assert doc.to_source(fragment=doc.text).snippet_only == reason
    assert result.limitation is None
    assert not isolated.exists()  # never saved


def test_a_site_that_blocks_us_is_asked_once_and_never_fetched_around():
    """Konkret24, AFP and Demagog answer 403 to the server IP, robots.txt included."""
    requests_seen = []

    def blocking(request):
        requests_seen.append((str(request.url), request.headers["user-agent"]))
        return httpx2.Response(403)

    async def go():
        return await search_web(
            "sankcje",
            provider=provider_returning("https://konkret24.tvn24.pl/a"),
            transport=httpx2.MockTransport(blocking),
        )

    [doc] = asyncio.run(go()).documents
    assert doc.snippet_only == BLOCKED
    assert (doc.publisher, doc.source_type) == ("Konkret24", "fact_check")
    # robots.txt, then the page once: no retry, no other user agent.
    assert requests_seen == [
        ("https://konkret24.tvn24.pl/robots.txt", safefetch.USER_AGENT),
        ("https://konkret24.tvn24.pl/a", safefetch.USER_AGENT),
    ]


@pytest.mark.parametrize(
    "routes",
    [
        {"www.gov.pl/p": httpx2.Response(404)},
        {"www.gov.pl/p": httpx2.Response(410)},
        {"www.gov.pl/p": httpx2.Response(401)},  # login wall: not public
        {"www.gov.pl/p": httpx2.Response(402)},  # payment wall
        {
            "www.gov.pl/p": httpx2.Response(
                302, headers={"location": "https://example.com/p"}
            ),
            "example.com/p": html(),
        },
        {
            "www.gov.pl/p": httpx2.Response(
                302, headers={"location": "https://example.com:8443/p"}
            )
        },
        {  # the site's opt-out: no copy from a search engine either
            "www.gov.pl/p": html(),
            "www.gov.pl/robots.txt": httpx2.Response(
                200, text="User-agent: *\nDisallow: /"
            ),
        },
        {
            "www.gov.pl/p": html(),
            "www.gov.pl/robots.txt": httpx2.Response(
                200, text="User-agent: *\nDisallow: /*p$"
            ),
        },
    ],
    ids=[
        "404",
        "410",
        "401",
        "402",
        "redirect-off-allowlist",
        "redirect-off-allowlist-other-port",
        "robots",
        "robots-wildcard",
    ],
)
def test_a_page_disallowed_gone_walled_or_off_the_allowlist_has_no_snippet(
    routes, isolated
):
    result = run(provider_returning("https://www.gov.pl/p"), routes)
    assert result.documents == []
    assert result.limitation == NOTHING_FETCHED
    assert not isolated.exists()


def test_a_snippet_without_text_is_no_source():
    def provider(query, *, domains, limit):
        return [SearchHit(url="https://www.gov.pl/p", title="t", snippet="  ")]

    result = run(provider, {"www.gov.pl/p": httpx2.Response(403)})
    assert result.documents == [] and result.limitation == NOTHING_FETCHED


def test_a_page_without_any_date_is_kept_undated(isolated):
    result = run(
        provider_returning("https://www.gov.pl/p"), {"www.gov.pl/p": html(UNDATED)}
    )
    [doc] = result.documents
    assert doc.published_at is None and doc.snippet_only is None
    assert "Rada UE przyjęła kolejny pakiet" in doc.text
    [stored] = cache.load_documents(isolated)
    assert stored.url == doc.url and stored.published_at is None


def test_a_pdf_hit_is_read_by_the_pypdf_worker(isolated):
    text = "Raport z kontroli wydatkow na obrone cywilna w latach 2023-2025. " * 5
    url = "https://www.nik.gov.pl/raport.pdf"
    routes = {"www.nik.gov.pl/raport.pdf": typed(pdf(text), "application/pdf")}
    provider = provider_returning_with_dates((url, date(2026, 5, 4)))
    [doc] = run(provider, routes).documents
    assert doc.snippet_only is None
    assert "Raport z kontroli wydatkow na obrone cywilna" in doc.text
    # The file has no title or date of its own: the search hit's.
    assert (doc.title, doc.published_at) == ("t", date(2026, 5, 4))
    assert (doc.source_type, doc.domain) == ("official", "www.nik.gov.pl")


def test_a_pdf_shows_the_search_title_over_its_file_name():
    text = "Raport z kontroli wydatkow na obrone cywilna w latach 2023-2025. " * 5
    body = pdf(text, title="Microsoft Word - raport_final_v3.docx")
    routes = {"www.gov.pl/raport.pdf": typed(body, "application/pdf")}
    [doc] = run(provider_returning("https://www.gov.pl/raport.pdf"), routes).documents
    assert doc.title == "t"


def test_a_pdf_over_the_page_cap_stands_as_its_snippet(monkeypatch):
    monkeypatch.setattr(websearch, "MAX_PAGE_BYTES", 100)
    routes = {"www.gov.pl/p": typed(pdf("x " * 200), "application/pdf")}
    [doc] = run(provider_returning("https://www.gov.pl/p"), routes).documents
    assert doc.snippet_only == TOO_BIG


@pytest.mark.parametrize(
    ("status", "snippet"),
    [(404, None), (410, None), (401, None), (402, None), (403, BLOCKED)],
)
def test_an_oversized_error_page_follows_the_status_rule(monkeypatch, status, snippet):
    monkeypatch.setattr(websearch, "MAX_PAGE_BYTES", 100)
    routes = {"www.gov.pl/p": httpx2.Response(status, content=b"x" * 500)}
    docs = run(provider_returning("https://www.gov.pl/p"), routes).documents
    assert [d.snippet_only for d in docs] == ([snippet] if snippet else [])


def test_a_page_we_read_wins_over_a_snippet_of_the_same_url():
    read = fetched_doc()
    snippet = read.model_copy(update={"text": "s", "snippet_only": BLOCKED})
    for found in ([read, snippet], [snippet, None, read]):
        assert websearch._one_per_url(found) == [read]


def fetched_doc():
    result = run(
        provider_returning("https://www.gov.pl/p"), {"www.gov.pl/p": html()}, save=False
    )
    return result.documents[0]


def test_cache_keeps_the_latest_fetch_of_a_url(tmp_path):
    path = tmp_path / "c.jsonl"
    old = fetched_doc()
    new = old.model_copy(
        update={
            "title": "Nowy tytuł",
            "fetched_at": old.fetched_at + timedelta(hours=1),
        }
    )
    cache.save_document(old, path)
    cache.save_document(new, path)
    [stored] = cache.load_documents(path)
    assert stored.title == "Nowy tytuł" and stored.fetched_at == new.fetched_at
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_cache_keeps_text_only_with_a_licence_and_drops_expired(tmp_path):
    path = tmp_path / "c.jsonl"
    doc = fetched_doc()
    licensed = doc.model_copy(
        update={"url": "https://www.gov.pl/l", "licence": "CC BY 4.0"}
    )
    expired = doc.model_copy(
        update={
            "url": "https://www.gov.pl/old",
            "fetched_at": datetime.now(UTC) - timedelta(days=cache.RETENTION_DAYS + 1),
        }
    )
    cache.save_document(expired, path)
    cache.save_document(licensed, path)
    cache.save_document(doc, path)
    stored = {d.url: d for d in cache.load_documents(path)}
    assert set(stored) == {licensed.url, doc.url}
    assert stored[licensed.url].text == licensed.text
    assert stored[doc.url].text == ""
    assert cache.delete_document(doc.url, path) is True
    assert cache.delete_document(doc.url, path) is False
    assert [d.url for d in cache.load_documents(path)] == [licensed.url]


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


@pytest.mark.parametrize("path", ["docs/sources.md", "docs/submission/sources.md"])
def test_source_list_documents_every_allowlisted_domain(path):
    sources = Path(path).read_text(encoding="utf-8")
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

    [doc] = asyncio.run(go()).documents
    assert doc.snippet_only == TOO_SLOW


DISALLOW_PRIVATE = httpx2.Response(200, text="User-agent: *\nDisallow: /private")


@pytest.mark.parametrize(
    ("routes", "checked"),
    [
        (  # same host, redirect to a disallowed path
            {
                "www.gov.pl/robots.txt": DISALLOW_PRIVATE,
                "www.gov.pl/p": httpx2.Response(302, headers={"location": "/private"}),
                "www.gov.pl/private": html(),
            },
            "https://www.gov.pl/robots.txt",
        ),
        (  # another allowlisted host whose robots.txt disallows everything
            {
                "www.gov.pl/p": httpx2.Response(
                    302, headers={"location": "https://www.sejm.gov.pl/x"}
                ),
                "www.sejm.gov.pl/robots.txt": httpx2.Response(
                    200, text="User-agent: *\nDisallow: /"
                ),
                "www.sejm.gov.pl/x": html(),
            },
            "https://www.sejm.gov.pl/robots.txt",
        ),
    ],
    ids=["same-host", "other-host"],
)
def test_robots_txt_is_checked_on_every_redirect_hop(routes, checked):
    seen = []
    result = run(provider_returning("https://www.gov.pl/p"), routes, seen=seen)
    assert result.documents == []  # disallowed: no snippet either
    assert checked in seen
    assert not [u for u in seen if u.endswith(("/private", "/x"))]


def test_a_malformed_redirect_loses_that_hit_only():
    routes = {
        "www.gov.pl/p": httpx2.Response(
            302, headers={"location": "https://[www.gov.pl/x"}
        ),
        "www.sejm.gov.pl/q": html(),
    }
    provider = provider_returning("https://www.gov.pl/p", "https://www.sejm.gov.pl/q")
    docs = {d.url: d.snippet_only for d in run(provider, routes).documents}
    assert docs == {
        "https://www.gov.pl/p": UNREADABLE,
        "https://www.sejm.gov.pl/q": None,
    }


@pytest.mark.parametrize("status", [429, 500, 503])
def test_unreadable_robots_txt_means_no_fetch(status):
    seen = []
    routes = {"www.gov.pl/robots.txt": httpx2.Response(status), "www.gov.pl/p": html()}
    result = run(provider_returning("https://www.gov.pl/p"), routes, seen=seen)
    # The site never said no: the label must not say it blocks us.
    assert [d.snippet_only for d in result.documents] == [NO_ANSWER]
    assert "https://www.gov.pl/p" not in seen
    assert "https://www.gov.pl" not in safefetch._robots  # retried later, not cached


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_robots_txt_answering_4xx_sets_no_rules(status):
    """RFC 9309 2.3.1.3; Python's RobotFileParser would read 401 and 403 as disallow-all."""
    seen = []
    routes = {"www.gov.pl/robots.txt": httpx2.Response(status), "www.gov.pl/p": html()}
    [doc] = run(provider_returning("https://www.gov.pl/p"), routes, seen=seen).documents
    assert doc.snippet_only is None and "https://www.gov.pl/p" in seen
    assert "https://www.gov.pl" in safefetch._robots  # cached like a parsed file


def test_oversized_robots_txt_and_page_are_refused(monkeypatch):
    big_robots = {
        "www.gov.pl/robots.txt": httpx2.Response(
            200, text="#" * (safefetch.ROBOTS_MAX_BYTES + 1)
        ),
        "www.gov.pl/p": html(),
    }
    [doc] = run(provider_returning("https://www.gov.pl/p"), big_robots).documents
    assert doc.snippet_only == NO_ANSWER

    monkeypatch.setattr(websearch, "MAX_PAGE_BYTES", 100)
    page_routes = {"www.gov.pl/p": html()}
    [doc] = run(provider_returning("https://www.gov.pl/p"), page_routes).documents
    assert doc.snippet_only == TOO_BIG


class RecordingBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self):
        self.connected = []

    async def connect_tcp(self, host, port, **kwargs):
        self.connected.append(host)
        return httpcore2.AsyncMockStream([])


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.5"],
        ["169.254.169.254"],
        ["::1"],
        ["::ffff:127.0.0.1"],
        ["93.184.216.34", "192.168.1.1"],  # one private answer is enough to refuse
    ],
)
def test_backend_refuses_hosts_resolving_to_non_public_addresses(
    monkeypatch, addresses
):
    async def fake_resolve(host, port):
        return addresses

    monkeypatch.setattr(safefetch, "resolve", fake_resolve)
    inner = RecordingBackend()
    with pytest.raises(httpcore2.ConnectError):
        asyncio.run(
            safefetch.PublicOnlyBackend(inner).connect_tcp("intranet.gov.pl", 443)
        )
    assert inner.connected == []


def test_backend_connects_to_the_address_it_checked(monkeypatch):
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])  # a rebinding resolver

    async def fake_resolve(host, port):
        return next(answers)

    monkeypatch.setattr(safefetch, "resolve", fake_resolve)
    inner = RecordingBackend()
    asyncio.run(safefetch.PublicOnlyBackend(inner).connect_tcp("www.gov.pl", 443))
    assert inner.connected == ["93.184.216.34"]


def test_default_transport_refuses_a_real_loopback_connection():
    async def go():
        async with safefetch.client(2) as http:
            await http.get("http://localhost/")

    with pytest.raises(httpx2.ConnectError, match="non-public"):
        asyncio.run(go())


def test_backend_falls_back_to_the_next_checked_address(monkeypatch):
    async def fake_resolve(host, port):
        return ["2001:db8::1", "93.184.216.34"]

    class FirstFails(RecordingBackend):
        async def connect_tcp(self, host, port, **kwargs):
            self.connected.append(host)
            if len(self.connected) == 1:
                raise httpcore2.ConnectTimeout("no route")
            return httpcore2.AsyncMockStream([])

    monkeypatch.setattr(safefetch, "resolve", fake_resolve)
    monkeypatch.setattr(safefetch, "is_public", lambda a: True)
    inner = FirstFails()
    asyncio.run(safefetch.PublicOnlyBackend(inner).connect_tcp("www.gov.pl", 443))
    assert inner.connected == ["2001:db8::1", "93.184.216.34"]


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


def test_robots_txt_section_for_our_bot_applies():
    seen = []
    rules = "User-agent: PrawdowidBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    routes = {
        "www.gov.pl/robots.txt": httpx2.Response(200, text=rules),
        "www.gov.pl/p": html(),
    }
    result = run(provider_returning("https://www.gov.pl/p"), routes, seen=seen)
    assert result.documents == []
    assert "https://www.gov.pl/p" not in seen


# --- #127: a fact-checker's own rating, from the ClaimReview markup of a page we read ---

REVIEW_PAGE = "https://demagog.org.pl/fake_news/sankcje-wobec-rosji/"
REVIEW_ROUTE = "demagog.org.pl/fake_news/sankcje-wobec-rosji/"
REVIEWED = "UE zniosła sankcje wobec Rosji."
RATING = factcheck.review_fragment("Fałsz", REVIEWED)


def claim_review(url=REVIEW_PAGE, rating="Fałsz", **more):
    review = {
        "@context": "https://schema.org",
        "@type": "ClaimReview",
        "claimReviewed": REVIEWED,
        "reviewRating": {"@type": "Rating", "alternateName": rating},
        **more,
    }
    return {**review, "url": url} if url else review


def marked_up(*blocks) -> str:
    """The test page with JSON-LD blocks (dicts or lists as JSON, strings as written)."""
    scripts = "".join(
        '<script type="application/ld+json">'
        f"{b if isinstance(b, str) else json.dumps(b)}</script>"
        for b in blocks
    )
    return PAGE.replace("</head>", f"{scripts}</head>")


def read_review_page(body, url=REVIEW_PAGE, route=REVIEW_ROUTE):
    [doc] = run(provider_returning(url), {route: html(body)}).documents
    assert "gazu skroplonego" in doc.text  # the page text is read as before
    return doc


@pytest.mark.parametrize(
    "blocks",
    [
        [claim_review()],
        [[{"@type": "Organization", "name": "Demagog"}, claim_review()]],
        [
            {
                "@context": "https://schema.org",
                "@graph": [{"@type": "WebPage"}, claim_review()],
            }
        ],
        [claim_review(url=None)],  # no url: a review on its own page
        [claim_review(url="http://www.demagog.org.pl/fake_news/sankcje-wobec-rosji")],
        [claim_review(url="/fake_news/sankcje-wobec-rosji/")],  # read against the page
        [claim_review(**{"@type": ["ClaimReview", "Review"]})],
        # A block that does not parse, before one that does.
        ['{"@type": "ClaimReview", "reviewRating": ', claim_review()],
    ],
    ids=[
        "object",
        "list",
        "graph",
        "no-url",
        "url-written-another-way",
        "relative-url",
        "type-list",
        "broken-block",
    ],
)
def test_a_fact_checkers_rating_is_read_from_its_page(blocks, isolated):
    doc = read_review_page(marked_up(*blocks))
    assert doc.reviews == [RATING]
    # Kept, like the page text, only under a licence: none is confirmed.
    [stored] = cache.load_documents(isolated)
    assert stored.reviews == [] and stored.text == ""


@pytest.mark.parametrize(
    "blocks",
    [
        [claim_review(url="https://demagog.org.pl/fake_news/inna-wypowiedz/")],
        [claim_review(url="/fake_news/inna-wypowiedz/")],
        [claim_review(url="https://[demagog.org.pl/fake_news")],
        ['{"@type": "ClaimReview", "reviewRating": '],
        [claim_review(rating="")],
        [{**claim_review(), "reviewRating": {"ratingValue": 1}}],
        [{**claim_review(), "@type": "Review"}],
        [],
    ],
    ids=[
        "another-page",
        "relative-url-of-another-page",
        "malformed-url",
        "broken",
        "blank-rating",
        "no-rating-name",
        "not-a-claim-review",
        "none",
    ],
)
def test_markup_that_is_no_rating_of_this_page_gives_none(blocks):
    assert read_review_page(marked_up(*blocks)).reviews == []


def test_ratings_are_read_only_from_a_fact_checkers_html_page(monkeypatch):
    official = read_review_page(
        marked_up(claim_review(url=None)), "https://www.gov.pl/p", "www.gov.pl/p"
    )
    assert official.source_type == "official" and official.reviews == []

    def never(page_html, page_url):
        raise AssertionError("a PDF has no markup to read")

    monkeypatch.setattr(websearch, "_claim_reviews", never)
    text = "Raport z kontroli wydatkow na obrone cywilna w latach 2023-2025. " * 5
    url = "https://demagog.org.pl/raport.pdf"
    routes = {"demagog.org.pl/raport.pdf": typed(pdf(text), "application/pdf")}
    [doc] = run(provider_returning(url), routes).documents
    assert doc.source_type == "fact_check" and doc.reviews == []


def test_markup_is_read_from_a_page_that_declares_its_encoding():
    page = '<?xml version="1.0" encoding="utf-8"?>' + marked_up(claim_review())
    assert websearch._claim_reviews(page, REVIEW_PAGE) == [RATING]
    assert websearch._claim_reviews("", REVIEW_PAGE) == []


def test_a_redirect_to_another_document_does_not_inherit_the_hits_date(isolated):
    routes = {
        "www.gov.pl/p": httpx2.Response(302, headers={"location": "/q"}),
        "www.gov.pl/q": html(UNDATED),
    }
    provider = provider_returning_with_dates(("https://www.gov.pl/p", date(2025, 1, 1)))
    [doc] = run(provider, routes).documents
    assert doc.url.endswith("/q") and doc.published_at is None


def test_a_redirect_to_a_pdf_shows_the_pdfs_own_title():
    text = "Raport z kontroli wydatkow na obrone cywilna w latach 2023-2025. " * 5
    routes = {
        "www.gov.pl/p": httpx2.Response(302, headers={"location": "/raport.pdf"}),
        "www.gov.pl/raport.pdf": typed(
            pdf(text, title="Raport NIK 2025"), "application/pdf"
        ),
    }
    [doc] = run(provider_returning("https://www.gov.pl/p"), routes).documents
    assert doc.title == "Raport NIK 2025"
