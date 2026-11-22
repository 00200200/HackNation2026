"""Every source a check uses, for the public page /zrodla (`GET /api/sources`).

Read from the files and constants the code itself uses, so the page cannot drift from it: the
catalogue (`corpus/catalog.yaml`, loaded by `corpus.catalog`), the built corpus
(`corpus/evidence.jsonl`, counted by `corpus.check.summarize` as `make corpus-check` counts it),
the web-search `ALLOWLIST` and the step 2 lookups with their endpoints, keys and switches.
"""

import os
from datetime import date
from functools import cache
from urllib.parse import urlsplit

from pydantic import BaseModel

from corpus.catalog import Status, load_catalog
from corpus.check import DOCS_PATH, summarize
from corpus.schema import MAX_TEXT_CHARS, read_jsonl
from prawdowid import euvsdisinfo, factcheck, govpl, websearch

# True once verify() searches corpus/evidence.jsonl (#74). tests/test_sources.py fails when
# pipeline.py calls search_corpus and this still says False, or the other way round.
CORPUS_IN_CHECKS = False
TAVILY_HOST = "api.tavily.com"  # tavily-python's default base URL


class Lookup(BaseModel):
    """One of the lookups step 2 runs for every checked claim (prawdowid/pipeline.py)."""

    id: str
    name: str
    description: str
    source_type: str | None  # None: the type of each result's domain
    host: str  # where the query goes
    needs_key: bool
    active: bool  # switched on, with its key set, in this deployment


class AllowedDomain(BaseModel):
    domain: str
    publisher: str | None  # None: the publisher named on the page
    source_type: str
    licence: str | None  # None: not confirmed, so page text is never stored


class CatalogueEntry(BaseModel):
    id: str
    publisher: str
    domain: str
    source_type: str
    status: Status
    licence: str | None  # None: "not checked" or UNCONFIRMED in the catalogue
    licence_url: str | None
    licence_checked: date | None
    storage: str
    max_chars: int | None  # full text is cut at this length; None for fragments
    update_interval: str | None  # "24h", "7d"; None where nothing is fetched
    records: int
    last_retrieved_at: str | None
    needs_key: bool  # collected only when the corpus build has an API key
    in_web_search: bool  # web search may return its pages: ALLOWLIST covers the domain
    note: str | None
    excluded_on: date | None
    excluded_reason: str | None


class CorpusSummary(BaseModel):
    records: int
    domains: int  # registered domains (Public Suffix List)
    strict_domains: int  # every *.gov.pl name counted as one domain
    source_types: dict[str, int]
    without_published_at: int  # records without a publication date read from the page
    last_retrieved_at: str | None
    in_checks: bool


class SourceList(BaseModel):
    lookups: list[Lookup]
    web_search: list[AllowedDomain]
    corpus: CorpusSummary
    catalogue: list[CatalogueEntry]


def source_list() -> SourceList:
    corpus, catalogue = _corpus()
    return SourceList(
        lookups=_lookups(),
        web_search=[
            AllowedDomain(
                domain=domain,
                publisher=entry.publisher,
                source_type=entry.source_type,
                licence=entry.licence,
            )
            for domain, entry in websearch.ALLOWLIST.items()
        ],
        corpus=corpus,
        catalogue=catalogue,
    )


def _lookups() -> list[Lookup]:
    """Read per request: a key set or removed shows on the next page load."""
    return [
        Lookup(
            id="factcheck",
            name="Google Fact Check Tools",
            description=(
                "Oceny twierdzeń opublikowane przez serwisy fact-checkingowe "
                "w znacznikach ClaimReview."
            ),
            source_type=factcheck.SOURCE_TYPE,
            host=_host(factcheck.URL),
            needs_key=True,
            active=bool(os.getenv(factcheck.KEY_ENV)),
        ),
        Lookup(
            id="euvsdisinfo",
            name="EUvsDisinfo",
            description=(
                "Baza opisanych przypadków prokremlowskiej dezinformacji, którą prowadzi "
                "Europejska Służba Działań Zewnętrznych. Trafienie to kontekst, "
                "samo nie przesądza o ocenie."
            ),
            source_type=websearch.ALLOWLIST["euvsdisinfo.eu"].source_type,
            host=_host(euvsdisinfo.URL),
            needs_key=True,
            active=bool(os.getenv(euvsdisinfo.KEY_ENV)),
        ),
        Lookup(
            id="govpl",
            name="Wyszukiwarka www.gov.pl",
            description=(
                "Komunikaty ministerstw i urzędów centralnych z serwisu www.gov.pl, "
                f"do {govpl.MAX_PAGES} stron na twierdzenie."
            ),
            source_type=websearch.ALLOWLIST["gov.pl"].source_type,
            host=_host(govpl.SEARCH_URL),
            needs_key=False,
            active=govpl.ENABLED,
        ),
        Lookup(
            id="web",
            name="Wyszukiwarka internetowa Tavily",
            description=(
                f"Zwraca strony tylko z {len(websearch.ALLOWLIST)} domen "
                "z listy poniżej."
            ),
            source_type=None,
            host=TAVILY_HOST,
            needs_key=True,
            active=bool(os.getenv(websearch.KEY_ENV)),
        ),
    ]


@cache
def _corpus() -> tuple[CorpusSummary, list[CatalogueEntry]]:
    """Read once: the image carries the catalogue and the corpus, and both change only on deploy."""
    docs = read_jsonl(DOCS_PATH)
    summary = summarize(docs)
    newest: dict[str, str] = {}
    for doc in docs:
        newest[doc.source_id] = max(newest.get(doc.source_id, ""), doc.retrieved_at)
    catalogue = [
        CatalogueEntry(
            id=s.id,
            publisher=s.publisher,
            domain=s.domain,
            source_type=s.source_type,
            status=s.status,
            licence=None
            if s.licence.startswith(("not checked", "UNCONFIRMED"))
            else s.licence,
            licence_url=s.licence_url,
            licence_checked=s.licence_checked,
            storage=s.storage,
            max_chars=s.params.get("max_chars", MAX_TEXT_CHARS)
            if s.storage == "full_text"
            else None,
            update_interval=s.update_interval if s.max_age else None,
            records=summary["sources"].get(s.id, 0),
            last_retrieved_at=newest.get(s.id),
            needs_key=bool(s.requires_env),
            in_web_search=websearch.allowed(f"https://{s.domain}/") is not None,
            note=s.note,
            excluded_on=s.excluded_on,
            excluded_reason=s.excluded_reason,
        )
        for s in load_catalog().sources
    ]
    corpus = CorpusSummary(
        records=summary["documents"],
        domains=len(summary["registered_domains"]),
        strict_domains=len(summary["strict_domains"]),
        source_types=summary["source_types"],
        without_published_at=summary["without_published_at"],
        last_retrieved_at=max(newest.values(), default=None),
        in_checks=CORPUS_IN_CHECKS,
    )
    return corpus, catalogue


def _host(url: str) -> str:
    return urlsplit(url).hostname or url
