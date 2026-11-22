"""Known-claim lookup in Google Fact Check Tools (claims:search).

Fact-checkers that publish ClaimReview markup may already have reviewed a claim. Each review comes
back as a `Source` candidate for reranking. Its `textualRating` and the reviewed claim travel in the
source's fragment ("Ocena fact-checkera: Fałsz." and the claim in a second paragraph), so the judge reads
them as data; the verdict is still set in code: a rating of the checked claim itself maps to one
(`judge.RATINGS`), a review of another claim is context. A missing key, quota error or outage is a
limitation, never a verdict.

One claim goes out as several short keys at once (`keys_for`, `search_keys`), not only as its
sentence.
Fact Check Explorer, which searches the same index, returned the reviews we probed for short keys
of names and nouns and nothing for the full claim sentence, even one equal to the review's claim
(#100). Whether claims:search with our key
behaves the same is UNCONFIRMED. The lookup is down (`FactCheckLookup.failed`) when the claim's own
key failed, the one request it made before #100, or when every key failed; other keys that failed
are named in a limitation, like a failed web query among several, and the hits that came back stand.

Docs: https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
(checked 2026-11-22: GET with query, languageCode, maxAgeDays, pageSize, pageToken, offset and
reviewPublisherSiteFilter; pageSize defaults to 10). maxAgeDays is not sent: an old review is still
evidence, and the judge flags archival material.
"""

import asyncio
import itertools
import logging
import os
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

import httpx2
from pydantic import BaseModel, ValidationError

from prawdowid.contract import Source
from prawdowid.privacy import mask_personal_data

log = logging.getLogger("prawdowid")

URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
KEY_ENV = "GOOGLE_FACTCHECK_API_KEY"
# httpx2 timeouts are per operation (connect, each read chunk), not per response: a server that
# trickles bytes never trips them. DEADLINE_S caps the whole lookup, retry included; the keys of
# one claim run at once, so it caps all of them.
TIMEOUT_S = 8
DEADLINE_S = 15
ATTEMPTS = 2  # first call plus one retry
# Reviews kept per claim once the keys are merged, whatever MAX_KEYS is: the page size of the
# lookup before #100. Fact Check hits come first among the candidates, so more of them would take
# rerank's MAX_DOCUMENTS from the web pages.
MAX_HITS = 10
# Per key when a claim has several: a short key such as a surname matches reviews of many other
# claims. A key alone gets a page of MAX_HITS.
PAGE_SIZE = 5
# Requests per claim (each may retry once); 1 sends only the claim, with the page size it had
# before #100. The quota of claims:search is UNCONFIRMED, and a key that runs out of it is a
# failed key.
MAX_KEYS = int(os.getenv("PRAWDOWID_FACTCHECK_MAX_KEYS") or 8)
if (
    MAX_KEYS < 1
):  # as `verifier.positive_int_env`: a bad count stops the service at startup
    raise ValueError(f"PRAWDOWID_FACTCHECK_MAX_KEYS must be at least 1, got {MAX_KEYS}")
# A quoted span shorter than this ("tak", "nie wiem") matches reviews of anything.
MIN_SPAN_WORDS = 3
SOURCE_TYPE = "fact_check"
# Start of the fragment's two lines: the rating (the review's own finding) and the claim it was
# given to (the disputed statement, not the review's words, so never a quotable finding).
RATING_PREFIX = "Ocena fact-checkera:"
CLAIM_PREFIX = "Sprawdzane twierdzenie:"
CLAIM_CHARS = 500

LOOKUP_UNAVAILABLE = (
    "Wyszukiwanie w bazie Google Fact Check było niedostępne, "
    "więc nie sprawdziliśmy, czy ktoś już zweryfikował to twierdzenie."
)
LOOKUP_PARTIAL = (
    "Część zapytań do bazy Google Fact Check ({failed} z {total}) się nie powiodła, "
    "więc mogliśmy nie znaleźć istniejącej weryfikacji tego twierdzenia."
)

WORD = re.compile(r"\w+")
# Text in quotation marks: a post's caption or a quoted statement, often what a fact-checker checked.
QUOTED = re.compile(r"[„“\"«»]([^„“”\"«»]+)[”“\"»«]")
# A capital letter after these (or at the start) opens a sentence or a quote, not a name.
OPENERS = '.!?:;„“"«»(['


class FactCheckHit(BaseModel):
    source: Source
    # The fact-checker's own rating ("False", "Fałsz", ...). The judge maps it to a verdict only
    # when the review is of the checked claim itself (`judge.RATINGS`).
    rating: str | None
    reviewed_claim: str | None


class FactCheckLookup(BaseModel):
    hits: list[FactCheckHit] = []
    # Set when the lookup could not run or some of its keys failed; goes to
    # ClaimResult.limitations.
    limitation: str | None = None
    # The lookup counts as down (`pipeline._deciders_down`): the request failed, or of several
    # keys the claim's own one or every one failed (`search_keys`).
    failed: bool = False


def unavailable() -> FactCheckLookup:
    """The lookup could not run: no hits, a limitation, down."""
    return FactCheckLookup(limitation=LOOKUP_UNAVAILABLE, failed=True)


def keys_for(
    claim: str, queries: Iterable[str] = (), texts: Iterable[str] = ()
) -> list[str]:
    """What claims:search gets for one claim, deduplicated (case and spacing), at most MAX_KEYS:
    the claim, the names in it, each span of MIN_SPAN_WORDS or more words in quotation marks in
    `texts` (the claim and its source sentence), then the search queries the extraction wrote.
    Personal data is masked again, as web search and gov.pl mask their queries."""
    spans = [span for text in texts for span in quoted(text)]
    unique: dict[str, str] = {}
    for key in [claim, names(claim), *spans, *queries]:
        key = _key(key)
        if key:
            unique.setdefault(key.casefold(), key)
    return list(unique.values())[:MAX_KEYS]


def _key(text: str) -> str:
    """A key as claims:search gets it: personal data masked, spacing collapsed."""
    return " ".join(mask_personal_data(text).split())


def names(text: str) -> str:
    """The capitalised words that open no sentence or quote ("Legii Warszawa Trybunał"): names of
    people, places and bodies, without the verbs that made Fact Check Explorer miss (#100). Empty
    with fewer than two: one name alone ("NATO") matches reviews of every claim about it."""
    found = []
    for m in WORD.finditer(text):
        before = text[: m.start()].rstrip()
        if m.group()[0].isupper() and before and before[-1] not in OPENERS:
            found.append(m.group())
    unique = list(dict.fromkeys(found))
    return " ".join(unique) if len(unique) > 1 else ""


def quoted(text: str) -> list[str]:
    """Spans of MIN_SPAN_WORDS or more words in quotation marks, edge punctuation dropped."""
    spans = [m.group(1).strip(" .,;:!?…") for m in QUOTED.finditer(text)]
    return [span for span in spans if len(WORD.findall(span)) >= MIN_SPAN_WORDS]


async def search_keys(
    claim: str,
    keys: Sequence[str],
    *,
    language: str | None = "pl",
    client: httpx2.AsyncClient | None = None,
) -> FactCheckLookup:
    """`search_claims` for every key at once, on one connection pool, each inside DEADLINE_S.

    Hits merge by review URL, round robin over the keys so that each key's best reviews come
    first, at most MAX_HITS. One review page can rate several claims under one URL, and rerank
    keeps one document per URL: the claim sharing most words with `claim` is kept.

    Unavailable when every key failed. When some failed, the limitation says how many, and the
    lookup is down only if the claim's own key is one of them: that is the request the lookup
    made before #100, so its failure is the outage it was then. The hits of the keys that
    answered stand either way: a review they found can still settle the claim.
    """
    if client is None:
        async with httpx2.AsyncClient() as http:
            return await search_keys(claim, keys, language=language, client=http)
    page_size = MAX_HITS if len(keys) == 1 else PAGE_SIZE

    async def one(key: str) -> FactCheckLookup:
        try:
            return await search_claims(
                key, language=language, client=client, page_size=page_size
            )
        except Exception:  # one broken key must not take the others' hits with it
            log.exception("factcheck key failed")
            return unavailable()

    lookups = await asyncio.gather(*(one(key) for key in keys))
    failed = [key for key, lookup in zip(keys, lookups, strict=True) if lookup.failed]
    if failed and len(failed) == len(keys):
        return unavailable()
    words = _words(claim)
    kept: dict[str, FactCheckHit] = {}
    for rank in itertools.zip_longest(*(lookup.hits for lookup in lookups)):
        for hit in filter(None, rank):
            url = str(hit.source.url)
            if url not in kept or _shared(words, hit) > _shared(words, kept[url]):
                kept[url] = hit
    log.info(
        "factcheck keys=%d hits_per_key=%s failed=%d reviews=%d",
        len(lookups),
        [len(lookup.hits) for lookup in lookups],
        len(failed),
        len(kept),
    )
    partial = LOOKUP_PARTIAL.format(failed=len(failed), total=len(keys))
    return FactCheckLookup(
        hits=list(kept.values())[:MAX_HITS],
        limitation=partial if failed else None,
        failed=_key(claim).casefold() in {_key(key).casefold() for key in failed},
    )


def _words(text: str) -> set[str]:
    return set(WORD.findall(text.casefold()))


def _shared(words: set[str], hit: FactCheckHit) -> int:
    return len(words & _words(hit.reviewed_claim or ""))


async def search_claims(
    claim: str,
    *,
    language: str | None = "pl",
    client: httpx2.AsyncClient | None = None,
    page_size: int = MAX_HITS,
) -> FactCheckLookup:
    """Look the claim up. `language=None` sends no language filter."""
    key = os.getenv(KEY_ENV)
    if not key:
        log.warning("factcheck lookup skipped: %s is not set", KEY_ENV)
        return unavailable()

    params = {"query": claim, "pageSize": page_size}
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
        return unavailable()
    if resp is None:
        return unavailable()

    # 4xx: bad or missing key, quota (429), bad request. Not worth a retry.
    if resp.status_code != 200:
        log.warning("factcheck unavailable: HTTP %d", resp.status_code)
        return unavailable()
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
        return unavailable()
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
            fragment=review_fragment(review.get("textualRating"), reviewed_claim),
        )
    except (KeyError, ValidationError):
        log.warning("factcheck review skipped: no usable url")
        return None
    return FactCheckHit(
        source=source, rating=review.get("textualRating"), reviewed_claim=reviewed_claim
    )


def review_fragment(rating: str | None, claim: str | None) -> str | None:
    """The fact-checker's rating and the claim it was given to, as data for rerank and the judge.

    No rating: None, so a bare review title (often the disputed claim itself) never stands as
    evidence on its own. The rating is one line with one final full stop, so the judge can tell
    whether a quote is the whole rating line (`judge._rating`).
    """
    rating = " ".join((rating or "").split()).rstrip(".").strip()
    if not rating:
        return None
    text = f"{RATING_PREFIX} {rating}."
    # One short paragraph: the judge must be able to tell the whole claim from the rating.
    claim = " ".join((claim or "").split())[:CLAIM_CHARS]
    return f"{text}\n\n{CLAIM_PREFIX} {claim}" if claim else text


def _date(value: str | None) -> date | None:
    """RFC3339 timestamp ("2014-10-02T15:01:23Z") to its date."""
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
