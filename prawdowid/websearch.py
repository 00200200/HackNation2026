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

import httpx2
import trafilatura
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from pydantic import BaseModel

from prawdowid import safefetch
from prawdowid.cache import Document, save_document
from prawdowid.privacy import mask_personal_data

log = logging.getLogger("prawdowid")


class Domain(NamedTuple):
    source_type: (
        str  # "official" (primary) or "fact_check" / "news" (reliable secondary)
    )
    # None: take the site name from the page (blanket entries such as gov.pl).
    publisher: str | None
    # Licence that allows us to keep the full text. None: UNCONFIRMED, the cache keeps metadata only.
    licence: str | None = None


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
MAX_PAGE_BYTES = 2_000_000
PAGE_BUDGET_S = 20  # robots.txt plus the page, retry included
SAVE_BUDGET_S = 10  # saving every fetched page to the source store
# Region "pl-pl" is passed to ddgs unchecked; UNCONFIRMED that every backend honours it.
REGION = "pl-pl"
# DuckDuckGo only (team decision). Not "auto": that falls back to scraping other engines.
DDGS_BACKEND = "duckduckgo"

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

    async with safefetch.client(FETCH_TIMEOUT_S, transport) as http:
        docs = await asyncio.gather(*(_fetch_bounded(u, http) for u in urls))
    # Two hits may redirect to the same page.
    docs = list({d.url: d for d in docs if d}.values())
    if save:
        await _save_all(docs)
    return WebSearch(documents=docs, limitation=None if docs else NOTHING_FETCHED)


async def _save_all(docs: list[Document]) -> None:
    """Best effort, bounded in total: a slow store never holds up the check."""
    try:
        async with asyncio.timeout(SAVE_BUDGET_S):
            for d in docs:
                await asyncio.to_thread(save_document, d)
    except TimeoutError:
        log.warning("source store save stopped: over %d s", SAVE_BUDGET_S)


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


def _allowed(url: str) -> bool:
    return allowed(url) is not None


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
    page = await _get_html(url, client)
    if page is None or not (entry := allowed(page.url)):
        return None
    extracted = await asyncio.to_thread(
        trafilatura.bare_extraction,
        page.text(),
        url=page.url,
        with_metadata=True,
        # No extensive search (URL, free text). htmldate still matches a plain date pattern on a
        # page without metadata. ponytail: accepted; a stricter metadata-only check if it misleads.
        date_extraction_params={"original_date": True, "extensive_search": False},
    )
    published = _date(extracted.date) if extracted else None
    if not extracted or not extracted.text or not extracted.title or not published:
        # No publication date: the brief requires one on every source.
        log.info("fetch skipped %s: no text, title or publication date", url)
        return None
    host = urlsplit(page.url).hostname or ""
    return Document(
        url=page.url,
        title=extracted.title,
        publisher=entry.publisher or extracted.sitename or host,
        published_at=published,
        fetched_at=datetime.now(UTC),
        source_type=entry.source_type,
        domain=host,
        licence=entry.licence,
        text=extracted.text,
    )


async def _get_html(url: str, client: httpx2.AsyncClient) -> safefetch.Page | None:
    """safefetch.get with one retry on a network error or 5xx. A 200 HTML page or None."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            page = await safefetch.get(
                url, client, allow=_allowed, max_bytes=MAX_PAGE_BYTES
            )
        except (safefetch.Blocked, httpx2.InvalidURL) as exc:
            log.info("fetch skipped %s: %s", url, exc)
            return None
        except httpx2.HTTPError as exc:  # network, timeout, non-public address
            log.warning("fetch attempt %d %s failed: %r", attempt, url, exc)
            continue
        if page.status >= 500:
            log.warning("fetch attempt %d %s: HTTP %d", attempt, url, page.status)
            continue
        # 401, 403, 429, paywalls: we never get around a block.
        if page.status != 200 or "html" not in page.content_type:
            log.info(
                "fetch skipped %s: HTTP %d %s", url, page.status, page.content_type
            )
            return None
        return page
    return None


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
