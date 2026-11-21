"""Step 2b: web search on allowlisted domains, page fetch, text extraction and the source cache.

The search provider is one function with the `SearchProvider` signature. Today it is DuckDuckGo
through the `ddgs` library (no key needed; it scrapes, there is no official DuckDuckGo web search
API). A Tavily, Brave or Exa wrapper with the same signature replaces it in one place.

A failed or empty search is a technical limit returned in `WebSearch.limitation`, never a verdict.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import NamedTuple, Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx2
import trafilatura
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from pydantic import BaseModel

from prawdowid.cache import Document, save_document
from prawdowid.privacy import mask_personal_data

log = logging.getLogger("prawdowid")


class Domain(NamedTuple):
    source_type: (
        str  # "official" (primary) or "fact_check" / "news" (reliable secondary)
    )
    # None: take the site name from the page (blanket entries such as gov.pl).
    publisher: str | None


# Why each domain qualifies, and its licence: docs/sources.md (a test keeps both in sync).
# A host matches its own entry or the closest parent entry: nik.gov.pl -> gov.pl.
ALLOWLIST = {
    "gov.pl": Domain("official", None),
    "sejm.gov.pl": Domain("official", "Kancelaria Sejmu"),
    "stat.gov.pl": Domain("official", "Główny Urząd Statystyczny"),
    "pkw.gov.pl": Domain("official", "Państwowa Komisja Wyborcza"),
    "prezydent.pl": Domain("official", "Kancelaria Prezydenta RP"),
    "nbp.pl": Domain("official", "Narodowy Bank Polski"),
    "europa.eu": Domain("official", None),
    "eur-lex.europa.eu": Domain("official", "EUR-Lex, Urząd Publikacji UE"),
    "euvsdisinfo.eu": Domain("official", "EUvsDisinfo (ESDZ)"),
    "nato.int": Domain("official", "NATO"),
    "who.int": Domain("official", "Światowa Organizacja Zdrowia"),
    "demagog.org.pl": Domain("fact_check", "Demagog"),
    "konkret24.tvn24.pl": Domain("fact_check", "Konkret24"),
    "fakenews.pl": Domain("fact_check", "FakeNews.pl"),
    "sprawdzam.afp.com": Domain("fact_check", "AFP Sprawdzam"),
    "pap.pl": Domain("news", "Polska Agencja Prasowa"),
}

SEARCH_TIMEOUT_S = 10
FETCH_TIMEOUT_S = 10
ATTEMPTS = 2  # first call plus one retry
MAX_REDIRECTS = 3
MAX_PAGE_BYTES = 2_000_000
PAGE_BUDGET_S = 20  # robots.txt plus the page, retry included
# Region "pl-pl" is passed to ddgs unchecked; UNCONFIRMED that every backend honours it.
REGION = "pl-pl"
# DuckDuckGo only (team decision). Not "auto": that falls back to scraping other engines.
DDGS_BACKEND = "duckduckgo"
USER_AGENT = "PrawdowidBot/0.1 (fact-checking demo, HackNation 2026)"

SEARCH_UNAVAILABLE = (
    "Wyszukiwarka internetowa nie odpowiedziała albo nie zwróciła wyników, "
    "więc nie szukaliśmy źródeł w sieci."
)
NOTHING_FETCHED = (
    "Wyszukiwarka znalazła strony, ale żadnej nie udało się pobrać i odczytać, "
    "więc nie mamy z nich źródeł."
)


class SearchHit(BaseModel):
    url: str
    title: str
    snippet: str


class SearchUnavailable(Exception):
    """The provider failed or returned nothing usable. Never a verdict."""


class SearchProvider(Protocol):
    def __call__(
        self, query: str, *, domains: Sequence[str], limit: int
    ) -> list[SearchHit]: ...


def ddg_search(query: str, *, domains: Sequence[str], limit: int) -> list[SearchHit]:
    """DuckDuckGo via ddgs. Domains go into the query as `site:` operators."""
    sites = " OR ".join(f"site:{d}" for d in domains)
    try:
        results = DDGS(timeout=SEARCH_TIMEOUT_S).text(
            f"{query} ({sites})",
            region=REGION,
            max_results=limit,
            backend=DDGS_BACKEND,
        )
    except DDGSException as exc:  # ddgs raises it for "no results" too: they look alike
        raise SearchUnavailable(str(exc)) from exc
    return [
        SearchHit(url=r["href"], title=r.get("title", ""), snippet=r.get("body", ""))
        for r in results
        if r.get("href")
    ]


class WebSearch(BaseModel):
    documents: list[Document] = []
    # Set when search or every fetch failed; goes to ClaimResult.limitations.
    limitation: str | None = None


def allowed(url: str) -> Domain | None:
    """The allowlist entry covering this URL's host, or None. http(s) only."""
    try:
        parts = urlsplit(url)
    except ValueError:  # e.g. "https://[www.gov.pl/x"
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    labels = parts.hostname.lower().removeprefix("www.").split(".")
    for i in range(len(labels) - 1):
        if entry := ALLOWLIST.get(".".join(labels[i:])):
            return entry
    return None


async def search_web(
    query: str,
    *,
    limit: int = 5,
    domains: Sequence[str] = tuple(ALLOWLIST),
    provider: SearchProvider = ddg_search,
    transport: httpx2.AsyncBaseTransport | None = None,  # tests only
    save: bool = True,
) -> WebSearch:
    """Search allowlisted domains, fetch and extract every hit, cache what was read."""
    hits = await _search(mask_personal_data(query), domains, limit, provider)
    if hits is None:
        return WebSearch(limitation=SEARCH_UNAVAILABLE)
    urls = list(dict.fromkeys(h.url for h in hits if allowed(h.url)))
    if not urls:
        return WebSearch(limitation=SEARCH_UNAVAILABLE)

    async with _client(transport) as http:
        docs = await asyncio.gather(*(_fetch_bounded(u, http) for u in urls))
    # Two hits may redirect to the same page.
    docs = list({d.url: d for d in docs if d}.values())
    if save:
        for d in docs:
            save_document(d)
    return WebSearch(documents=docs, limitation=None if docs else NOTHING_FETCHED)


async def _search(
    query: str, domains: Sequence[str], limit: int, provider: SearchProvider
) -> list[SearchHit] | None:
    """Provider call in a thread, bounded, with one retry. None when every attempt failed."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(provider, query, domains=domains, limit=limit),
                SEARCH_TIMEOUT_S + 5,
            )
        except (SearchUnavailable, TimeoutError) as exc:
            log.warning("web search attempt %d failed: %r", attempt, exc)
    return None


class OffAllowlist(httpx2.RequestError):
    pass


async def _only_allowlisted(request: httpx2.Request) -> None:
    """Runs before every request, redirect hops included, so no hop leaves the allowlist."""
    if not allowed(str(request.url)):
        raise OffAllowlist(f"{request.url} is not allowlisted", request=request)


def _client(transport: httpx2.AsyncBaseTransport | None) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=FETCH_TIMEOUT_S,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        event_hooks={"request": [_only_allowlisted]},
        transport=transport,
    )


async def _fetch_bounded(url: str, client: httpx2.AsyncClient) -> Document | None:
    """The client timeout bounds each read, not a page trickled in slowly: cap the whole page."""
    try:
        async with asyncio.timeout(PAGE_BUDGET_S):
            return await fetch_document(url, client)
    except TimeoutError:
        log.warning("fetch skipped %s: over %d s", url, PAGE_BUDGET_S)
        return None


async def fetch_document(url: str, client: httpx2.AsyncClient) -> Document | None:
    """Fetch an allowlisted HTML page and extract it. None when it cannot be used."""
    entry = allowed(url)
    if not entry or not await _robots_allow(url, client):
        return None
    html, final_url = await _get_html(url, client)
    if html is None:
        return None
    # Fallback for a client without the hook: a redirect may leave the allowlist.
    if not (entry := allowed(final_url)):
        log.info("fetch skipped %s: redirected off the allowlist", url)
        return None
    page = await asyncio.to_thread(
        trafilatura.bare_extraction,
        html,
        url=final_url,
        with_metadata=True,
        # No extensive search (URL, free text). htmldate still matches a plain date pattern on a
        # page without metadata. ponytail: accepted; a stricter metadata-only check if it misleads.
        date_extraction_params={"original_date": True, "extensive_search": False},
    )
    published = _date(page.date) if page else None
    if not page or not page.text or not page.title or not published:
        # No publication date: the brief requires one on every source.
        log.info("fetch skipped %s: no text, title or publication date", url)
        return None
    return Document(
        url=final_url,
        title=page.title,
        publisher=entry.publisher
        or page.sitename
        or urlsplit(final_url).hostname
        or "",
        published_at=published,
        fetched_at=datetime.now(UTC),
        source_type=entry.source_type,
        domain=urlsplit(final_url).hostname or "",
        text=page.text,
    )


async def _get_html(url: str, client: httpx2.AsyncClient) -> tuple[str | None, str]:
    """GET with one retry on a network error or 5xx. HTML under the size cap only."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 500:
                    log.warning(
                        "fetch attempt %d %s: HTTP %d", attempt, url, resp.status_code
                    )
                    continue
                # 401, 403, 429, paywalls: we never get around a block.
                if resp.status_code != 200:
                    log.info("fetch skipped %s: HTTP %d", url, resp.status_code)
                    return None, url
                if "html" not in resp.headers.get("content-type", ""):
                    log.info("fetch skipped %s: not HTML", url)
                    return None, url
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_PAGE_BYTES:
                        log.info("fetch skipped %s: over %d bytes", url, MAX_PAGE_BYTES)
                        return None, url
                return body.decode(resp.encoding or "utf-8", errors="replace"), str(
                    resp.url
                )
        # Deterministic: the same request would fail again.
        except (OffAllowlist, httpx2.TooManyRedirects, httpx2.InvalidURL) as exc:
            log.info("fetch skipped %s: %r", url, exc)
            return None, url
        except httpx2.HTTPError as exc:  # network, timeout
            log.warning("fetch attempt %d %s failed: %r", attempt, url, exc)
    return None, url


_robots: dict[str, RobotFileParser] = {}


async def _robots_allow(url: str, client: httpx2.AsyncClient) -> bool:
    """Respect robots.txt. A missing file allows everything; an unreadable one, nothing."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        parser = RobotFileParser()
        try:
            resp = await client.get(f"{origin}/robots.txt")
        except (httpx2.HTTPError, httpx2.InvalidURL) as exc:
            log.warning("robots.txt %s unreadable: %r", origin, exc)
            return False
        if resp.status_code >= 500:
            return False  # not cached: retry on the next page
        if resp.status_code in (401, 403):
            parser.disallow_all = True  # same rule as RobotFileParser.read()
        else:
            parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        _robots[origin] = parser
    return _robots[origin].can_fetch(USER_AGENT, url)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
