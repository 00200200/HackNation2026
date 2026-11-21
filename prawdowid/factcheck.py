"""Known-claim lookup in Google Fact Check Tools (claims:search).

Fact-checkers that publish ClaimReview markup may already have reviewed a claim. Each review comes
back as a `Source` candidate for reranking. Its `textualRating` is only a signal kept next to the
source: the verdict is still set in code. A missing key, quota error or outage is a limitation,
never a verdict.

Docs: https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
"""

import asyncio
import logging
import os
from datetime import UTC, date, datetime

import httpx2
from pydantic import BaseModel, ValidationError

from prawdowid.contract import Source

log = logging.getLogger("prawdowid")

URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
KEY_ENV = "GOOGLE_FACTCHECK_API_KEY"
# httpx2 timeouts are per operation (connect, each read chunk), not per response: a server that
# trickles bytes never trips them. DEADLINE_S caps the whole lookup, retry included.
TIMEOUT_S = 8
DEADLINE_S = 15
ATTEMPTS = 2  # first call plus one retry
PAGE_SIZE = 10
SOURCE_TYPE = "fact_check"

LOOKUP_UNAVAILABLE = (
    "Wyszukiwanie w bazie Google Fact Check było niedostępne, "
    "więc nie sprawdziliśmy, czy ktoś już zweryfikował to twierdzenie."
)


class FactCheckHit(BaseModel):
    source: Source
    # The fact-checker's own rating ("False", "Fałsz", ...). A signal, never a verdict.
    rating: str | None
    reviewed_claim: str | None


class FactCheckLookup(BaseModel):
    hits: list[FactCheckHit] = []
    # Set when the lookup could not run; goes to ClaimResult.limitations.
    limitation: str | None = None


async def search_claims(
    claim: str,
    *,
    language: str | None = "pl",
    client: httpx2.AsyncClient | None = None,
) -> FactCheckLookup:
    """Look the claim up. `language=None` sends no language filter."""
    key = os.getenv(KEY_ENV)
    if not key:
        log.warning("factcheck lookup skipped: %s is not set", KEY_ENV)
        return FactCheckLookup(limitation=LOOKUP_UNAVAILABLE)

    params = {"query": claim, "pageSize": PAGE_SIZE}
    if language:
        params["languageCode"] = language
    # Header, not ?key=, so the key never shows up in logged URLs.
    headers = {"x-goog-api-key": key}

    try:
        async with asyncio.timeout(DEADLINE_S):
            if client:
                resp = await _get(client, params, headers)
            else:
                async with httpx2.AsyncClient() as http:
                    resp = await _get(http, params, headers)
    except TimeoutError:
        log.warning("factcheck unavailable: no answer within %s s", DEADLINE_S)
        return FactCheckLookup(limitation=LOOKUP_UNAVAILABLE)
    if resp is None:
        return FactCheckLookup(limitation=LOOKUP_UNAVAILABLE)

    # 4xx: bad or missing key, quota (429), bad request. Not worth a retry.
    if resp.status_code != 200:
        log.warning("factcheck unavailable: HTTP %d", resp.status_code)
        return FactCheckLookup(limitation=LOOKUP_UNAVAILABLE)
    fetched_at = datetime.now(UTC)
    try:
        hits = [
            hit
            for found in resp.json().get("claims") or []
            for review in found.get("claimReview") or []
            if (hit := _to_hit(found, review, fetched_at))
        ]
    except (ValueError, AttributeError, TypeError):
        log.warning(
            "factcheck unavailable: response does not match the documented shape"
        )
        return FactCheckLookup(limitation=LOOKUP_UNAVAILABLE)
    return FactCheckLookup(hits=hits)


async def _get(
    http: httpx2.AsyncClient, params: dict, headers: dict
) -> httpx2.Response | None:
    """GET with one retry on a network error, timeout or 5xx. None when every attempt failed."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            resp = await http.get(
                URL, params=params, headers=headers, timeout=TIMEOUT_S
            )
        except httpx2.RequestError as exc:  # network, timeout, broken body encoding
            log.warning("factcheck attempt %d failed: %r", attempt, exc)
            continue
        if resp.status_code < 500:
            return resp
        log.warning("factcheck attempt %d: HTTP %d", attempt, resp.status_code)
    return None


def _to_hit(found: dict, review: dict, fetched_at: datetime) -> FactCheckHit | None:
    publisher = review.get("publisher") or {}
    reviewed_claim = found.get("text")
    try:
        source = Source(
            # Never the reviewed claim: it is the disputed statement, not the review's words.
            title=review.get("title") or review["url"],
            publisher=publisher.get("name") or publisher.get("site") or "",
            published_at=_date(review.get("reviewDate")),
            fetched_at=fetched_at,
            url=review["url"],
            source_type=SOURCE_TYPE,
            # No excerpt of the review page yet; the reviewed claim stays in FactCheckHit.
            fragment=None,
        )
    except (KeyError, ValidationError):
        log.warning("factcheck review skipped: no usable url")
        return None
    return FactCheckHit(
        source=source, rating=review.get("textualRating"), reviewed_claim=reviewed_claim
    )


def _date(value: str | None) -> date | None:
    """RFC3339 timestamp ("2014-10-02T15:01:23Z") to its date."""
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
