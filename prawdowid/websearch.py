"""Step 2b: web search on allowlisted domains, page fetch, text extraction and the source cache.

The search provider is one function with the `SearchProvider` signature. It is Tavily's official
`/search` endpoint through `tavily-python` (https://docs.tavily.com/documentation/api-reference/endpoint/search),
restricted server-side to `ALLOWLIST` via `include_domains`. A Brave or Exa wrapper with the same
signature replaces it in one place.

A failed or empty search is a technical limit returned in `WebSearch.limitation`, never a verdict.

Every hit is fetched by us (HTML through trafilatura, PDF through the link input's pypdf worker).
When our fetch cannot use an allowlisted page (the site answers 403 or 429, does not answer in
time, the page is too big or unreadable) the hit stays as the search provider's own title and
extract, marked `snippet_only` with the reason: we never fetch around a block, and such a snippet
is never saved. A page that robots.txt disallows (the site's opt-out), that is gone (404, 410),
sits behind a login or payment wall (401, 402) or redirects off the allowlist is dropped. A page without any publication date is kept with `published_at=None`; the judge adds a
limitation and never counts it as strong evidence.
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
from pydantic import BaseModel, HttpUrl, ValidationError
from tavily import (
    BadRequestError,
    InvalidAPIKeyError,
    TavilyClient,
    UsageLimitExceededError,
)
from tavily.errors import ForbiddenError
from tavily.errors import TimeoutError as TavilyTimeoutError

from prawdowid import link, safefetch
from prawdowid.cache import Document, save_document
from prawdowid.privacy import mask_personal_data

log = logging.getLogger("prawdowid")


class Domain(NamedTuple):
    # "official" (primary) or "fact_check" / "news" (reliable secondary, "news" a news agency);
    # "media": a newspaper or portal, one publisher like any other; "disinfo_database": a
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
    "konkret24.tvn24.pl": Domain("fact_check", "Konkret24"),
    "fakenews.pl": Domain("fact_check", "FakeNews.pl"),
    "sprawdzam.afp.com": Domain("fact_check", "AFP Sprawdzam"),
    # Answers 403 to our server, so in practice only its search snippets reach the judge (#76).
    # Publisher names match the other lookups (Fact Check's "Demagog", the corpus's Pravda), so
    # one fact-checker found twice is still one origin in judge.decide.
    "demagog.org.pl": Domain("fact_check", "Demagog"),
    "pravda.org.pl": Domain("fact_check", "Stowarzyszenie Pravda"),
    # Its fact-checks (/kategoria/prawda-czy-falsz) have flat URLs like every other article, so
    # no URL pattern tells them apart: the whole site is media. Not "news": that type is for a
    # news agency, whose own finding can stand against a reliable source (judge._conflicting).
    "oko.press": Domain("media", "OKO.press"),
    "pap.pl": Domain("news", "Polska Agencja Prasowa"),
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
    skip_hosts: frozenset[str] = frozenset(),
) -> WebSearch:
    """Search allowlisted domains, fetch and extract every hit, cache what was read.

    `skip_hosts`: hosts another lookup covers (www.gov.pl, by `govpl`). Filtered here, not with
    Tavily's `exclude_domains`: Tavily drops the `www.` prefix, so excluding www.gov.pl there also
    drops sejm.gov.pl, stat.gov.pl and every other *.gov.pl site (tested live 2026-11-21).
    """
    # Skipped hosts take result slots (www.gov.pl filled 14 of 15 for a GIS claim on 2026-11-21):
    # ask for twice as many, keep `limit`. One Tavily basic search costs the same either way.
    hits = await _search(
        mask_personal_data(query), domains, limit * 2 if skip_hosts else limit, provider
    )
    if hits is None:
        return WebSearch(limitation=SEARCH_UNAVAILABLE)
    by_url = {h.url: h for h in hits if allowed(h.url)}
    if not by_url:
        return WebSearch(limitation=SEARCH_UNAVAILABLE)
    by_url = {
        u: h
        for u, h in by_url.items()
        if (urlsplit(u).hostname or "").lower() not in skip_hosts
    }
    if not by_url:  # every hit is covered by another lookup: an answer, not a failure
        return WebSearch()
    by_url = dict(list(by_url.items())[:limit])

    async with safefetch.client(FETCH_TIMEOUT_S, transport) as http:
        docs = _one_per_url(
            await asyncio.gather(*(_document(h, http) for h in by_url.values()))
        )
    if save:  # a search snippet is not our copy of a page: never saved
        await _save_all([d for d in docs if not d.snippet_only])
    return WebSearch(documents=docs, limitation=None if docs else NOTHING_FETCHED)


def _one_per_url(found: list[Document | None]) -> list[Document]:
    """Two hits may redirect to the same page: a page we read wins over a snippet of it."""
    docs: dict[str, Document] = {}
    for d in found:
        if d and (d.url not in docs or docs[d.url].snippet_only):
            docs[d.url] = d
    return list(docs.values())


async def _save_all(docs: list[Document]) -> None:
    """Best effort, bounded in total: a slow store never holds up the check."""
    try:
        async with asyncio.timeout(SAVE_BUDGET_S):
            for d in docs:
                await asyncio.to_thread(save_document, d)
    except TimeoutError:
        log.warning("source store save stopped: over %d s", SAVE_BUDGET_S)
    except OSError as exc:  # after TimeoutError, its subclass
        log.warning("source store save failed: %s", type(exc).__name__)


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


# Why our own fetch could not use a page search found; shown with its snippet as
# "fragment z wyników wyszukiwarki; <reason>".
BLOCKED = "strona nie pozwala na pobranie"
NO_ANSWER = "strona nie odpowiedziała"
TOO_SLOW = "strona nie odpowiedziała na czas"
TOO_BIG = "strona jest za duża do pobrania"
UNREADABLE = "nie udało się odczytać treści strony"


class Unread(Exception):
    """Our fetch cannot use the page. `reason` (Polish) labels the hit's search snippet instead;
    None when the snippet may not stand in either: robots.txt disallows the page, it is gone,
    behind a login or payment wall, or leaves the allowlist."""

    def __init__(self, problem: str, reason: str | None):
        super().__init__(problem)
        self.reason = reason


async def _document(hit: SearchHit, client: httpx2.AsyncClient) -> Document | None:
    """The hit's page as we read it, else its search snippet (`_snippet`).

    The client timeout bounds each read, not a page trickled in slowly: PAGE_BUDGET_S caps the
    whole page.
    """
    try:
        async with asyncio.timeout(PAGE_BUDGET_S):
            return await _read(hit.url, client, hit.published_date, hit.title)
    except TimeoutError:
        problem, reason = f"over {PAGE_BUDGET_S:g} s", TOO_SLOW
    except Unread as exc:
        problem, reason = str(exc), exc.reason
    doc = _snippet(hit, reason) if reason else None
    log.info(
        "fetch skipped %s: %s%s", hit.url, problem, "; snippet kept" if doc else ""
    )
    return doc


def _snippet(hit: SearchHit, reason: str) -> Document | None:
    """The search provider's own title and extract of a page we could not read. Nothing is
    fetched for it, and it is never saved. Type and publisher come from the allowlist."""
    entry = allowed(hit.url)
    title, text = hit.title.strip(), hit.snippet.strip()
    if not entry or not title or not text:
        return None
    try:
        HttpUrl(hit.url)  # what Source.url will require
    except ValidationError:
        return None
    host = urlsplit(hit.url).hostname or ""
    return Document(
        url=hit.url,
        title=title,
        publisher=entry.publisher or host,
        published_at=hit.published_date,
        fetched_at=datetime.now(UTC),
        source_type=entry.source_type,
        domain=host,
        licence=entry.licence,
        text=text,
        snippet_only=reason,
    )


async def fetch_document(
    url: str, client: httpx2.AsyncClient, fallback_published: date | None = None
) -> Document | None:
    """Fetch an allowlisted HTML page or PDF and extract it. None when it cannot be used.

    `fallback_published`: the search provider's own publication date, used only when the page
    itself carries none (common on Polish gov/news pages without date metadata). A page with no
    date anywhere is kept with `published_at=None`.
    """
    try:
        return await _read(url, client, fallback_published)
    except Unread as exc:
        log.info("fetch skipped %s: %s", url, exc)
        return None


async def _read(
    url: str,
    client: httpx2.AsyncClient,
    fallback_published: date | None,
    fallback_title: str = "",
) -> Document:
    """Fetch and extract. The page's own title and date first, the search hit's as fallback;
    for a PDF the hit's title first, since a file's own is often its name ("Microsoft Word - …")."""
    page = await _get_page(url, client)
    if not (entry := allowed(page.url)):
        raise Unread(f"{page.url} is not allowlisted", None)
    text, title, sitename, published = await _extract(page)
    if _media_type(page) == link.PDF_TYPE:
        title = fallback_title.strip() or title
    else:
        title = title or fallback_title.strip()
    if not text or not title:
        raise Unread("no text or title", UNREADABLE)
    host = urlsplit(page.url).hostname or ""
    return Document(
        url=page.url,
        title=title,
        publisher=entry.publisher or sitename or host,
        published_at=published or fallback_published,
        fetched_at=datetime.now(UTC),
        source_type=entry.source_type,
        domain=host,
        licence=entry.licence,
        text=text,
    )


async def _extract(
    page: safefetch.Page,
) -> tuple[str | None, str | None, str | None, date | None]:
    """Text, title, site name and publication date of an HTML page or a PDF."""
    if _media_type(page) == link.PDF_TYPE:
        # The link input's pypdf path: a child process with its own page and memory ceilings.
        try:
            pdf = await link.extract(page.body, link.PDF_TYPE, page.url)
        except link.Refusal:
            return None, None, None, None
        return pdf.text, pdf.title, pdf.publisher, pdf.published_at
    extracted = await asyncio.to_thread(
        trafilatura.bare_extraction,
        page.text(),
        url=page.url,
        with_metadata=True,
        # No extensive search (URL, free text). htmldate still matches a plain date pattern on a
        # page without metadata. ponytail: accepted; a stricter metadata-only check if it misleads.
        date_extraction_params={"original_date": True, "extensive_search": False},
    )
    if not extracted:
        return None, None, None, None
    return extracted.text, extracted.title, extracted.sitename, _date(extracted.date)


async def _get_page(url: str, client: httpx2.AsyncClient) -> safefetch.Page:
    """safefetch.get with one retry on a network error or 5xx: a 200 HTML page or PDF, else
    Unread."""
    problem = "no answer"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            page = await safefetch.get(
                url, client, allow=_allowed, max_bytes=MAX_PAGE_BYTES
            )
        except (safefetch.Blocked, httpx2.InvalidURL) as exc:
            # Too many redirects, a malformed URL or another port: unreadable.
            raise Unread(str(exc), _REFUSALS.get(type(exc), UNREADABLE)) from exc
        except httpx2.HTTPError as exc:  # network, timeout, non-public address
            log.warning("fetch attempt %d %s failed: %r", attempt, url, exc)
            problem = repr(exc)
            continue
        if page.status >= 500:
            log.warning("fetch attempt %d %s: HTTP %d", attempt, url, page.status)
            problem = f"HTTP {page.status}"
            continue
        # 401, 402, 403, 429: we never get around a block.
        if page.status != 200:
            raise Unread(f"HTTP {page.status}", _status_reason(page.status))
        if "html" not in _media_type(page) and _media_type(page) != link.PDF_TYPE:
            raise Unread(f"type {page.content_type!r}", UNREADABLE)
        return page
    raise Unread(problem, NO_ANSWER)


# What a safefetch refusal means for the snippet. None, no snippet: the page leaves the allowlist,
# or robots.txt disallows it (the site opted out of crawlers: no copy from a search engine either).
_REFUSALS = {
    safefetch.NotAllowed: None,
    safefetch.Disallowed: None,
    safefetch.RobotsUnreachable: NO_ANSWER,
    safefetch.TooLarge: TOO_BIG,
}


def _status_reason(status: int) -> str | None:
    """Why a non-200 answer cannot be read. None, so no snippet either: a page that is gone (its
    snippet is stale) or behind a login or payment wall (its content is not public)."""
    if status in (401, 402, 404, 410):
        return None
    return BLOCKED if 400 <= status < 500 else UNREADABLE


def _media_type(page: safefetch.Page) -> str:
    return page.content_type.split(";")[0].strip().lower()


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
