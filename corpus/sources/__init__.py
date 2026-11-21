"""Collectors by the name used in `corpus/catalog.yaml` (`collector:`)."""

from collections.abc import Callable

from corpus.catalog import Source
from corpus.http import PoliteClient
from corpus.schema import Doc
from corpus.sources.apis import (
    collect_imgw_warnings,
    collect_odyseusz,
    collect_sejm_eli,
)
from corpus.sources.eurlex import collect_eurlex
from corpus.sources.feeds import collect_claim_reviews, collect_feed
from corpus.sources.keyed import collect_euvsdisinfo, collect_google_factcheck
from corpus.sources.lists import collect_news_list, collect_pages

COLLECTORS: dict[str, Callable[[Source, PoliteClient], list[Doc]]] = {
    "news_list": collect_news_list,
    "pages": collect_pages,
    "feed": collect_feed,
    "claim_reviews": collect_claim_reviews,
    "sejm_eli": collect_sejm_eli,
    "imgw_warnings": collect_imgw_warnings,
    "odyseusz": collect_odyseusz,
    "eurlex": collect_eurlex,
    "google_factcheck": collect_google_factcheck,
    "euvsdisinfo": collect_euvsdisinfo,
}
