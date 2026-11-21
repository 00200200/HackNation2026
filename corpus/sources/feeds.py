"""RSS and Atom feeds (feedparser)."""

import logging
from datetime import UTC, datetime

import feedparser

from corpus.catalog import Source
from corpus.extract import plain_text
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import Doc
from corpus.sources.base import Item, items_to_docs

log = logging.getLogger("corpus")


def parse_feed(xml: str) -> list[Item]:
    """Entries of a feed; empty when the body is not a feed."""
    items = []
    for entry in feedparser.parse(xml).entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        lead = plain_text(entry.get("summary"))
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


def _feed_items(source: Source, client: PoliteClient) -> tuple[list[Item], str]:
    """Entries of all feeds in params.feeds (e.g. WordPress `?paged=N` pages, in order). A failing
    feed after the first ends the reading (the archive has run out, or the site stopped
    answering) and keeps what was read."""
    items: dict[str, Item] = {}
    listed_at = ""
    for url in source.params["feeds"]:
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
        for item in parse_feed(page.text):
            items.setdefault(item.url, item)
    if not items:
        raise FetchError("the feeds have no entries")
    return list(items.values()), listed_at


def collect_feed(source: Source, client: PoliteClient) -> list[Doc]:
    """params: feeds, max_docs. Excerpt sources keep the feed summary only."""
    items, listed_at = _feed_items(source, client)
    return items_to_docs(source, client, items, listed_at)
