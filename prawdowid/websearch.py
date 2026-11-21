"""Step 2b: web search on allowlisted domains, page fetch, text extraction and the source cache.

The search provider is one function with the `SearchProvider` signature. It is Tavily's official
`/search` endpoint through `tavily-python` (https://docs.tavily.com/documentation/api-reference/endpoint/search),
restricted server-side to `ALLOWLIST` via `include_domains`. A Brave or Exa wrapper with the same
signature replaces it in one place.

A failed or empty search is a technical limit returned in `WebSearch.limitation`, never a verdict.
"""

import asyncio
import logging
import os
from collections.abc import Sequence
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import NamedTuple, Protocol
from urllib.parse import urlsplit

import httpx2
import requests
import trafilatura
from pydantic import BaseModel
from tavily import (
    BadRequestError,
    InvalidAPIKeyError,
    TavilyClient,
    UsageLimitExceededError,
)
from tavily.errors import ForbiddenError
from tavily.errors import TimeoutError as TavilyTimeoutError

from prawdowid import safefetch
from prawdowid.cache import Document, save_document
from prawdowid.privacy import mask_personal_data

log = logging.getLogger("prawdowid")


class Domain(NamedTuple):
    # "official" (primary) or "fact_check" / "news" (reliable secondary); "disinfo_database": a
    # known-narrative match, context that never decides on its own.
    source_type: str
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
    # Official EU body, but a match only says the claim resembles a documented narrative: not a
    # reliable type in judge.decide, so it needs a second independent origin to count.
    "euvsdisinfo.eu": Domain("disinfo_database", "EUvsDisinfo (ESDZ)"),
    "nato.int": Domain("official", "NATO"),
    "who.int": Domain("official", "Światowa Organizacja Zdrowia"),
    "demagog.org.pl": Domain("fact_check", "Demagog"),
    "konkret24.tvn24.pl": Domain("fact_check", "Konkret24"),
    "fakenews.pl": Domain("fact_check", "FakeNews.pl"),
    "sprawdzam.afp.com": Domain("fact_check", "AFP Sprawdzam"),
    "pap.pl": Domain("news", "Polska Agencja Prasowa"),
    # Crisis and safety sources from the team's list (corpus/seeds.txt); gov.pl hosts fall under gov.pl.
    "policja.pl": Domain("official", "Policja"),
    "cert.pl": Domain("official", "CERT Polska (NASK)"),
    "imgw.pl": Domain("official", "IMGW-PIB"),
    "portalpasazera.pl": Domain("primary", "PKP Polskie Linie Kolejowe"),
    "kgsok.pl": Domain("primary", "Straż Ochrony Kolei"),
}

SEARCH_TIMEOUT_S = 10
FETCH_TIMEOUT_S = 10
ATTEMPTS = 2  # first call plus one retry
MAX_PAGE_BYTES = 2_000_000
# Both caps keep one claim inside the check's time budget (#11): DuckDuckGo took ~20 s to say
# "no results" over two attempts in the full eval on f1e1684.
SEARCH_BUDGET_S = float(
    os.getenv("PRAWDOWID_WEB_SEARCH_BUDGET_S") or 10
)  # retry included
PAGE_BUDGET_S = float(
    os.getenv("PRAWDOWID_PAGE_BUDGET_S") or 8
)  # robots.txt and page; reads time out at 10 s, so no retry after a stall
SAVE_BUDGET_S = 10  # saving every fetched page to the source store

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
    published_date: date | None = None


class SearchUnavailable(Exception):
    """The provider failed or returned nothing usable. Never a verdict."""


class SearchProvider(Protocol):
    def __call__(
        self, query: str, *, domains: Sequence[str], limit: int
    ) -> list[SearchHit]: ...


_TAVILY_ERRORS = (
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    UsageLimitExceededError,
    TavilyTimeoutError,
    requests.RequestException,  # network errors and non-2xx the SDK doesn't map itself
)
_client: TavilyClient | None = None


def tavily_search(query: str, *, domains: Sequence[str], limit: int) -> list[SearchHit]:
    """Tavily /search, restricted server-side to `domains`.
    https://docs.tavily.com/documentation/api-reference/endpoint/search
    """
    global _client
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise SearchUnavailable("TAVILY_API_KEY not set")
    if _client is None:
        _client = TavilyClient(api_key=api_key)
    try:
        response = _client.search(
            query,
            max_results=limit,
            include_domains=list(domains),
            include_domains_mode="restrict",
            language="pl",
            include_published_date=True,
            timeout=SEARCH_TIMEOUT_S,
        )
    except _TAVILY_ERRORS as exc:
        raise SearchUnavailable(str(exc)) from exc
    return [
        SearchHit(
            url=r["url"],
            title=r.get("title") or "",
            snippet=r.get("content") or "",
            published_date=_tavily_date(r.get("published_date")),
        )
        for r in response["results"]
        if r.get("url")
    ]


def _tavily_date(value: str | None) -> date | None:
    """Tavily sends either an RFC 2822 string or a plain ISO date, undocumented which."""
    if parsed := _date(value):
        return parsed
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


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
    provider: SearchProvider = tavily_search,
    transport: httpx2.AsyncBaseTransport | None = None,  # tests only
    save: bool = True,
) -> WebSearch:
    """Search allowlisted domains, fetch and extract every hit, cache what was read."""
    hits = await _search(mask_personal_data(query), domains, limit, provider)
    if hits is None:
        return WebSearch(limitation=SEARCH_UNAVAILABLE)
    by_url = {h.url: h for h in hits if allowed(h.url)}
    if not by_url:
        return WebSearch(limitation=SEARCH_UNAVAILABLE)

    async with safefetch.client(FETCH_TIMEOUT_S, transport) as http:
        docs = await asyncio.gather(
            *(_fetch_bounded(u, http, h.published_date) for u, h in by_url.items())
        )
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
    """Provider call in a thread, with one retry while SEARCH_BUDGET_S lasts. None when every
    attempt failed or the budget ran out."""
    try:
        async with asyncio.timeout(SEARCH_BUDGET_S):
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            provider, query, domains=domains, limit=limit
                        ),
                        SEARCH_TIMEOUT_S + 5,
                    )
                except (SearchUnavailable, TimeoutError) as exc:
                    log.warning("web search attempt %d failed: %r", attempt, exc)
    except TimeoutError:
        log.warning("web search unavailable: over %g s", SEARCH_BUDGET_S)
    return None


def _allowed(url: str) -> bool:
    return allowed(url) is not None


async def _fetch_bounded(
    url: str, client: httpx2.AsyncClient, fallback_published: date | None = None
) -> Document | None:
    """The client timeout bounds each read, not a page trickled in slowly: cap the whole page."""
    try:
        async with asyncio.timeout(PAGE_BUDGET_S):
            return await fetch_document(url, client, fallback_published)
    except TimeoutError:
        log.warning("fetch skipped %s: over %g s", url, PAGE_BUDGET_S)
        return None


async def fetch_document(
    url: str, client: httpx2.AsyncClient, fallback_published: date | None = None
) -> Document | None:
    """Fetch an allowlisted HTML page and extract it. None when it cannot be used.

    `fallback_published`: the search provider's own publication date, used only when the page
    itself carries none (common on Polish gov/news pages without date metadata).
    """
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
    published = (_date(extracted.date) if extracted else None) or fallback_published
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
