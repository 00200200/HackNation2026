"""Step 2 lookup in the www.gov.pl site search: ministries, RCB alerts, government statements.

`GET https://www.gov.pl/api/data/search?query=<q>&page=1&size=<n>` is the search endpoint used by
the www.gov.pl site itself. It is undocumented and needs no key; its stability is UNCONFIRMED.
Each hit is a page under `/web/<unit>/...`; we fetch it through the same safe fetch and extraction
as web search pages (`websearch.fetch_document`: SSRF guard, robots.txt, byte cap, trafilatura).

Polite by design: one search per gov.pl query of a claim, small `size`, one retry, our usual
User-Agent, at most `MAX_CONCURRENT` gov.pl requests at a time, searches cached in process for 10 minutes. A
block, rate limit or login page is never worked around. A failure is a limitation, never a verdict.
"""

import asyncio
import json
import logging
import os
import time
import weakref
from collections import OrderedDict
from datetime import date
from urllib.parse import urlsplit

import httpx2

from prawdowid import safefetch, websearch
from prawdowid.cache import Document
from prawdowid.privacy import mask_personal_data
from prawdowid.websearch import WebSearch

log = logging.getLogger("prawdowid")

ENABLED = os.getenv("PRAWDOWID_GOVPL", "1") != "0"
SITE = "https://www.gov.pl"
SEARCH_URL = f"{SITE}/api/data/search"
# What the site search covers; sejm.gov.pl and other *.gov.pl sites are not.
HOSTS = frozenset({"gov.pl", "www.gov.pl"})
MAX_QUERIES = 2  # gov.pl searches per claim, whatever the model wrote
SIZE = 5  # hits per query
MAX_PAGES = 5  # pages fetched per claim, across its queries
# gov.pl requests in flight at once, whole process. Separate slots, so slow pages of one claim
# never use up another claim's search budget while it waits.
MAX_CONCURRENT = {"search": 2, "page": 3}
TIMEOUT_S = 8
ATTEMPTS = 2  # first call plus one retry
SEARCH_BUDGET_S = 10  # all searches of one claim, retries included
MAX_SEARCH_BYTES = 500_000
CACHE_SIZE = 256  # queries kept in process
CACHE_TTL_S = 600  # new alerts and statements show up after at most 10 minutes

# Units under www.gov.pl/web/<path>; any other path keeps the site name the page gives itself.
PUBLISHERS = {
    "rcb": "Rządowe Centrum Bezpieczeństwa",
    "mswia": "Ministerstwo Spraw Wewnętrznych i Administracji",
    "kgpsp": "Komenda Główna Państwowej Straży Pożarnej",
    "gis": "Główny Inspektorat Sanitarny",
    "mon": "Ministerstwo Obrony Narodowej",
    "mi": "Ministerstwo Infrastruktury",
    "msz": "Ministerstwo Spraw Zagranicznych",
    "dyplomacja": "Ministerstwo Spraw Zagranicznych",
    "premier": "Kancelaria Prezesa Rady Ministrów",
    "zdrowie": "Ministerstwo Zdrowia",
    "finanse": "Ministerstwo Finansów",
}

LOOKUP_UNAVAILABLE = (
    "Wyszukiwarka serwisu gov.pl nie odpowiedziała, "
    "więc nie sprawdziliśmy komunikatów ministerstw i urzędów na gov.pl."
)

_searches: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_gates: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def is_govpl(url: str) -> bool:
    """A page the gov.pl site search covers, so web search leaves it out."""
    host = urlsplit(url).hostname or ""
    return host.lower() in HOSTS


async def search_govpl(
    queries: list[str], *, transport: httpx2.AsyncBaseTransport | None = None
) -> WebSearch:
    """Search www.gov.pl for each query, fetch the top pages. `transport` is for tests."""
    queries = [q for q in (q.strip() for q in queries) if q][:MAX_QUERIES]
    if not queries:
        return WebSearch()
    async with safefetch.client(TIMEOUT_S, transport) as http:
        try:
            async with asyncio.timeout(SEARCH_BUDGET_S):
                results = await asyncio.gather(
                    *(_search(mask_personal_data(q), http) for q in queries)
                )
        except TimeoutError:
            log.warning("gov.pl search over %g s", SEARCH_BUDGET_S)
            return WebSearch(limitation=LOOKUP_UNAVAILABLE)
        if all(r is None for r in results):
            return WebSearch(limitation=LOOKUP_UNAVAILABLE)
        hits: dict[str, dict] = {}
        for hit in (h for r in results if r for h in r):  # query order, best hit first
            if isinstance(hit.get("url"), str) and hit["url"].startswith("/web/"):
                hits.setdefault(SITE + hit["url"], hit)
        picked = list(hits.items())[:MAX_PAGES]
        docs = await asyncio.gather(*(_page(u, h, http) for u, h in picked))
    docs = list({d.url: d for d in docs if d}.values())
    # Found nothing is an answer, not a failure: no limitation.
    return WebSearch(documents=docs)


async def _search(query: str, http: httpx2.AsyncClient) -> list[dict] | None:
    """Hits of one query, cached for CACHE_TTL_S; None when every attempt failed."""
    cached = _searches.get(query)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        _searches.move_to_end(query)
        return cached[1]
    url = str(httpx2.URL(SEARCH_URL, params={"query": query, "page": 1, "size": SIZE}))
    for attempt in range(1, ATTEMPTS + 1):
        try:
            async with _gate("search"):
                page = await safefetch.get(
                    url, http, allow=is_govpl, max_bytes=MAX_SEARCH_BYTES
                )
        except (safefetch.Blocked, httpx2.InvalidURL) as exc:
            log.info("gov.pl search refused: %s", exc)
            return None
        except httpx2.HTTPError as exc:
            log.warning("gov.pl search attempt %d failed: %r", attempt, exc)
            continue
        if page.status >= 500:
            log.warning("gov.pl search attempt %d: HTTP %d", attempt, page.status)
            continue
        if page.status != 200:  # 403, 429, a login: never worked around
            log.warning("gov.pl search refused: HTTP %d", page.status)
            return None
        try:
            hits = json.loads(page.body)["results"]
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("gov.pl search answer not usable: %r", exc)
            return None
        if not isinstance(hits, list):
            return None
        hits = [h for h in hits if isinstance(h, dict)]
        if hits:  # an empty answer may be a gap in indexing: asked again next time
            _searches[query] = (time.monotonic(), hits)
            _searches.move_to_end(query)
            if len(_searches) > CACHE_SIZE:
                _searches.popitem(last=False)
        return hits
    return None


async def _page(url: str, hit: dict, http: httpx2.AsyncClient) -> Document | None:
    """The hit's page as a Document: publisher from the unit path, date from the search."""
    published = _date(hit.get("publishDate"))
    try:
        async with _gate("page"), asyncio.timeout(websearch.PAGE_BUDGET_S):
            doc = await websearch.fetch_document(url, http, published)
    except TimeoutError:
        log.warning("gov.pl page skipped %s: over %g s", url, websearch.PAGE_BUDGET_S)
        return None
    if doc is None:
        return None
    update = {"published_at": published or doc.published_at}
    if publisher := PUBLISHERS.get(str(hit.get("path") or "").lower()):
        update["publisher"] = publisher
    if isinstance(hit.get("title"), str) and hit["title"].strip():
        update["title"] = hit["title"].strip()
    return doc.model_copy(update=update)


def _gate(kind: str) -> asyncio.Semaphore:
    """Semaphores per event loop: a Semaphore is bound to the loop it first waits in."""
    gates = _gates.setdefault(asyncio.get_running_loop(), {})
    if kind not in gates:
        gates[kind] = asyncio.Semaphore(MAX_CONCURRENT[kind])
    return gates[kind]


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None
