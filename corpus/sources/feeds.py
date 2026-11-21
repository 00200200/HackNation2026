"""RSS and Atom feeds (feedparser), and fact-check pages with schema.org ClaimReview markup."""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser

from corpus.catalog import Source
from corpus.check import disinfo_domains
from corpus.extract import json_ld, node_text, parse_html, plain_text
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import CitedLink, Doc, clip, registered_domain
from corpus.sources.base import (
    PLATFORMS,
    Item,
    Stopped,
    items_to_docs,
    make_doc,
    moved_away,
)

log = logging.getLogger("corpus")

CLAIM_CHARS = 600  # the reviewed claim is the claimant's words; long ones are cut
CLAIM_IN_TEXT = 250  # in `text`, so the rating and the justification always fit
MAX_LINKS = 5  # keeps docs.jsonl well under the 10 MB push limit


def parse_feed(xml: str, drop: str | None = None) -> list[Item]:
    """Entries of a feed; empty when the body is not a feed. `drop` is a regex removed from
    summaries (feed boilerplate)."""
    items = []
    for entry in feedparser.parse(xml).entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        lead = plain_text(entry.get("summary"))
        if drop:
            lead = re.sub(drop, "", lead).strip()
        title = plain_text(entry.get("title"))
        if entry.get("link") and title:
            items.append(
                Item(
                    url=entry["link"],
                    title=title,
                    published_at=datetime(*stamp[:6], tzinfo=UTC).isoformat()
                    if stamp
                    else None,
                    lead=lead,
                )
            )
    return items


def feed_urls(params: dict) -> list[str]:
    """params.feeds, each also as `?paged=2..pages` (WordPress feed pages) when pages > 1."""
    urls = []
    for url in params["feeds"]:
        urls.append(url)
        urls += [f"{url}?paged={n}" for n in range(2, params.get("pages", 1) + 1)]
    return urls


def _feed_items(source: Source, client: PoliteClient) -> tuple[list[Item], str]:
    """Entries of all feed pages. A failing page after the first ends the paging (the archive
    has run out, or the site stopped answering) and keeps what was read."""
    items: dict[str, Item] = {}
    listed_at = ""
    for url in feed_urls(source.params):
        try:
            page = client.get(url, max_age=source.max_age)
        except Blocked:
            raise
        except FetchError as exc:
            if not items:
                raise
            log.warning(
                "%s: feed page failed (%s), keeping earlier pages: %s",
                source.id,
                url,
                exc,
            )
            break
        listed_at = listed_at or page.fetched_at
        for item in parse_feed(page.text, source.params.get("drop")):
            items.setdefault(item.url, item)
    if not items:
        raise FetchError("the feeds have no entries")
    return list(items.values()), listed_at


def collect_feed(source: Source, client: PoliteClient) -> list[Doc]:
    """params: feeds, pages, max_docs, drop. Excerpt sources keep the feed summary only."""
    items, listed_at = _feed_items(source, client)
    return items_to_docs(source, client, items, listed_at)


@dataclass(frozen=True)
class Review:
    """What a fact-check page says about one claim, from its ClaimReview markup."""

    claim: str | None
    rating: str | None  # verbatim, as the publisher labels it
    author: str | None
    first_appearance: str | None
    summary: str  # the publisher's justification (or the page description)
    links: list[CitedLink] = field(default_factory=list)


TRACKING = re.compile(r"^(utm(_\w*)?|srsltid|fbclid|gclid|mc_cid|mc_eid)$")
# Abbreviations the site's editor turned into links ("m.in." = "między innymi").
NOT_LINKS = frozenset({"m.in", "m.st"})


def without_tracking(url: str) -> str:
    """Drop tracking parameters (utm*, srsltid, fbclid...) and the fragment, leaving every other
    part of the query exactly as written. By hand, because courlan's strict mode also drops
    ordinary parameters."""
    parts = urlsplit(url)
    kept = [
        segment
        for segment in parts.query.split("&")
        if segment and not TRACKING.match(segment.split("=", 1)[0])
    ]
    return urlunsplit(parts._replace(query="&".join(kept), fragment=""))


def _node(value) -> dict:
    """A schema.org value that should be an object: tolerate a list or a bare string."""
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def _one(value):
    """A single value where a list may come instead: its first element."""
    return (value[0] if value else None) if isinstance(value, list) else value


def _words(value) -> str | None:
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    return " ".join(str(value).split()) or None if value not in (None, "") else None


def parse_review(
    html: str,
    url: str,
    summary_xpath: str | None = None,
    banned: frozenset[str] = frozenset(),
) -> Review:
    """ClaimReview fields, plus the justification and the links in it, when the page marks it
    (`summary_xpath`). Links to social platforms, archives of posts, the site itself and domains
    on the disinformation list (`banned`) are left out: they are not sources."""
    root = parse_html(html)
    review = _node(json_ld(root, "ClaimReview"))
    item = _node(review.get("itemReviewed"))
    rating = _node(review.get("reviewRating"))
    claim = _words(review.get("claimReviewed"))
    summary_nodes = root.xpath(summary_xpath) if summary_xpath else []
    summary = " ".join(node_text(n) for n in summary_nodes)
    if not summary:
        description = root.xpath('//meta[@property="og:description"]/@content')
        summary = " ".join(description[0].split()) if description else ""
    own = registered_domain(url)
    links: dict[str, CitedLink] = {}
    for node in summary_nodes:
        for anchor in node.xpath(".//a[@href]"):
            href = without_tracking(urljoin(url, anchor.get("href").strip()))
            domain = registered_domain(href)
            skip = PLATFORMS | banned | NOT_LINKS | {own}
            if href.startswith("http") and domain not in skip:
                links.setdefault(href, CitedLink(url=href, text=node_text(anchor)))
    return Review(
        claim=clip(claim, CLAIM_CHARS)[0] if claim else None,
        rating=_words(_one(rating.get("alternateName") or rating.get("ratingValue"))),
        author=_words(_one(_node(item.get("author")).get("name"))),
        first_appearance=_words(_one(_node(item.get("firstAppearance")).get("url"))),
        summary=summary,
        links=list(links.values())[:MAX_LINKS],
    )


def review_text(review: Review, publisher: str) -> str:
    """Rating first, then the claim (cut so the justification still fits the fragment), then the
    justification. The rating keeps the publisher's wording; only a final full stop is dropped."""
    parts = []
    if review.rating:
        parts.append(f"Ocena ({publisher}): {review.rating.rstrip('.')}.")
    if review.claim:
        parts.append(
            f"Sprawdzane twierdzenie: „{clip(review.claim, CLAIM_IN_TEXT)[0]}”"
        )
    if review.summary:
        parts.append(review.summary)
    return " ".join(parts)


def collect_claim_reviews(source: Source, client: PoliteClient) -> list[Doc]:
    """Feeds list the fact-checks; each page gives the claim, the rating, the justification and
    the cited sources. The text keeps at most a short fragment; the article is never stored.

    params: feeds, pages, max_docs, summary_xpath, public_claimants (store who made the claim
    and where: only for public statements of public figures).
    """
    items, _ = _feed_items(source, client)
    public = source.params.get("public_claimants", False)
    banned = frozenset(disinfo_domains())
    docs: list[Doc] = []
    for item in items[: source.params.get("max_docs", len(items))]:
        try:
            page = client.get(item.url)
        except Blocked as exc:
            raise Stopped(str(exc), docs) from exc
        except FetchError as exc:
            log.warning("%s: skipped %s (%s)", source.id, item.url, exc)
            continue
        if moved_away(item.url, page.url):
            log.warning(
                "%s: skipped %s (redirects to %s)", source.id, item.url, page.url
            )
            continue
        review = parse_review(
            page.text, page.url, source.params.get("summary_xpath"), banned
        )
        doc = make_doc(
            source,
            url=page.url,
            title=item.title,
            text=review_text(review, source.publisher),
            published_at=item.published_at,
            retrieved_at=page.fetched_at,
            claim=review.claim,
            rating=review.rating,
            claim_author=review.author if public else None,
            claim_source=review.first_appearance if public else None,
            cited_links=review.links,
        )
        if doc is None:
            log.warning("%s: no claim or description in %s", source.id, item.url)
        else:
            docs.append(doc)
    return docs
