"""Sources that need a key from the team: Google Fact Check Tools API and EUvsDisinfo.

Neither could be run against the live service while this was written (no key, no token).
The request and response shapes follow the official reference and the organiser's how-to:
- https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
- https://euvsdisinfo.eu/public-docs/How_to_grab_all_Articles_and_Cases_from_disinfo.pdf
Check the first real run by hand before trusting the numbers.
"""

import asyncio
import json
import logging
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastmcp import Client

from corpus.catalog import Source
from corpus.extract import plain_text
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import Doc, clip, parse_date, registered_domain
from corpus.sources.base import PLATFORMS, Stopped, make_doc

log = logging.getLogger("corpus")

FACTCHECK_API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
EUVSDISINFO_MCP = "https://euvsdisinfo-mcp-server.vercel.app/mcp"
MCP_PAGE = 100  # the server's maximum page size
CLAIM_CHARS = 600
CLAIM_IN_TEXT = 250  # in `text`, so the rating always fits the fragment


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# -- Google Fact Check Tools API ----------------------------------------------------------------


def review_text(claim: str, rating: str, publisher: str) -> str:
    """Rating first, in the publisher's wording (only a final full stop dropped), then the claim
    cut so the rating always fits the fragment."""
    return (
        f"Ocena ({publisher}): {rating.rstrip('.')}. "
        f"Sprawdzane twierdzenie: „{clip(claim, CLAIM_IN_TEXT)[0]}”"
    )


def review_docs(
    source: Source, claims: list[dict], retrieved_at: str, site: str
) -> list[Doc]:
    """One record per review published on `site`: the claim, the rating and the link. The
    claimant is not kept: it is often a private account."""
    docs = []
    for claim in claims:
        claim_text = " ".join(str(claim.get("text") or "").split())
        for review in claim.get("claimReview") or []:
            publisher = (review.get("publisher") or {}).get("name")
            url = review.get("url") or ""
            if not (claim_text and publisher) or registered_domain(url) != site:
                continue
            rating = review.get("textualRating") or None
            if not rating:  # a claim without the verdict would be the false claim alone
                continue
            short_claim = clip(claim_text, CLAIM_CHARS)[0]
            text = review_text(short_claim, rating, publisher)
            doc = make_doc(
                source,
                url=url,
                title=review.get("title") or claim_text,
                text=text,
                published_at=parse_date(review.get("reviewDate")),
                retrieved_at=retrieved_at,
                publisher=publisher,
                claim=short_claim,
                rating=rating,
            )
            if doc is not None:
                docs.append(doc)
    return docs


def collect_google_factcheck(source: Source, client: PoliteClient) -> list[Doc]:
    """Reviews by the admitted fact-checkers. params: publisher_sites, max_pages."""
    headers = {"X-Goog-Api-Key": os.environ[source.requires_env]}
    docs = []
    for site in source.params["publisher_sites"]:
        token = None
        for _ in range(source.params.get("max_pages", 3)):
            query = {
                "languageCode": source.language,
                "reviewPublisherSiteFilter": site,
                "pageSize": 100,
            }
            if token:
                query["pageToken"] = token
            try:
                page = client.get(
                    f"{FACTCHECK_API}?{urlencode(query)}",
                    headers=headers,
                    check_robots=False,
                    max_age=source.max_age,
                )
            except Blocked as exc:
                raise Stopped(str(exc), docs) from exc
            data = json.loads(page.text)
            docs += review_docs(source, data.get("claims") or [], page.fetched_at, site)
            token = data.get("nextPageToken")
            if not token:
                break
    return docs


# -- EUvsDisinfo (MCP server, streamable HTTP) --------------------------------------------------


async def fetch_cases(
    target, token: str | None, limit: int, pause: float = 1.0
) -> list[dict]:
    """Page through the `cases` tool. `target` is the server URL (or a server object in tests)."""
    cases: list[dict] = []
    async with Client(target, auth=token, timeout=30) as mcp:
        while len(cases) < limit:
            result = await mcp.call_tool(
                "cases", {"offset": len(cases), "limit": MCP_PAGE}
            )
            page = result.structured_content or {}
            batch = page.get("cases") or []
            cases += batch
            if not batch or not page.get("hasNextPage"):
                break
            await asyncio.sleep(pause)
    return cases[:limit]


def disinfo_domains(cases: list[dict]) -> dict[str, int]:
    """Registered domain of every outlet linked in `linksToDisinformation` -> number of cases.

    Used only for the neutral warning of ADR 0001, section 5: never as evidence or a verdict.
    """
    counts: Counter[str] = Counter()
    for case in cases:
        links = case.get("linksToDisinformation") or []
        domains = {registered_domain(link["url"]) for link in links if link.get("url")}
        counts.update(d for d in domains if d and d not in PLATFORMS)
    return dict(counts.most_common())


def case_doc(source: Source, case: dict, retrieved_at: str) -> Doc | None:
    claim, fact = plain_text(case.get("claim")), plain_text(case.get("fact"))
    if not (case.get("url") and case.get("title") and claim):
        return None
    published = None
    if isinstance(stamp := case.get("date"), int | float):
        seconds = stamp / 1000 if stamp > 1e11 else stamp  # tolerate milliseconds
        published = datetime.fromtimestamp(seconds, UTC).date().isoformat()
    # The disproof comes first, so a cut fragment never holds the false claim alone.
    text = f"Disproof (EUvsDisinfo): {fact}\n" if fact else ""
    text += f"Disinformation claim: {claim}"
    return make_doc(
        source,
        url=case["url"],
        title=case["title"],
        text=text,
        published_at=published,
        retrieved_at=retrieved_at,
        claim=clip(claim, CLAIM_CHARS)[0],
    )


def _about_poland(case: dict) -> bool:
    return any(c.get("title") == "Poland" for c in case.get("countries") or [])


def collect_euvsdisinfo(source: Source, client: PoliteClient) -> list[Doc]:
    """Cases as incident records plus the list of domains they link to.

    params: scan_cases (how many to read), max_docs (how many become records; cases about
    Poland first, then the newest), domains_out (path of the domain list).
    """
    token = os.environ[source.requires_env]
    cases = asyncio.run(
        fetch_cases(EUVSDISINFO_MCP, token, source.params["scan_cases"])
    )
    if not cases:  # keep the last domain list rather than replace it with an empty one
        raise FetchError("EUvsDisinfo returned no cases")
    retrieved_at = _now()
    Path(source.params["domains_out"]).write_text(
        json.dumps(
            {
                "built_at": retrieved_at,
                "source": "EUvsDisinfo cases, field linksToDisinformation",
                "cases_scanned": len(cases),
                "use": "Neutral warning only. A domain on this list never decides a verdict.",
                "domains": disinfo_domains(cases),
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    cases.sort(key=lambda c: (_about_poland(c), c.get("date") or 0), reverse=True)
    docs = (
        case_doc(source, case, retrieved_at)
        for case in cases[: source.params["max_docs"]]
    )
    return [doc for doc in docs if doc is not None]
