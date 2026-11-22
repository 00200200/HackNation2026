"""Shared pieces of the collectors: one record builder and the list-item flow."""

import logging
import re
from dataclasses import dataclass

from corpus.catalog import Source
from corpus.extract import main_text
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import (
    EXCERPT_CHARS,
    MAX_TEXT_CHARS,
    Doc,
    clip,
    doc_id,
    mask_personal,
    registered_domain,
    squash,
)

log = logging.getLogger("corpus")

# Platforms host everyone. A link to a post there is not a source, and is often a private person.
PLATFORMS = frozenset(
    {
        "archive.is",
        "archive.li",
        "archive.md",
        "archive.org",
        "archive.ph",
        "archive.today",
        "archive.vn",
        "bitchute.com",
        "dzen.ru",
        "facebook.com",
        "fb.watch",
        "ghostarchive.org",
        "instagram.com",
        "linkedin.com",
        "odysee.com",
        "ok.ru",
        "perma.cc",
        "pinterest.com",
        "reddit.com",
        "rumble.com",
        "rutube.ru",
        "t.me",
        "telegra.ph",
        "telegram.me",
        "telegram.org",
        "threads.com",
        "threads.net",
        "tiktok.com",
        "twitter.com",
        "vk.com",
        "wykop.pl",
        "x.com",
        "youtu.be",
        "youtube.com",
    }
)
# Job adverts are not evidence and list contact persons with direct phone numbers.
JOB_ADVERT = re.compile(
    r"(?i)\bnab[oó]r\b|naborze|rekrutac|oferta pracy|konkurs na stanowisko|wolne stanowisk"
)


class Stopped(Exception):
    """The site started refusing the collector (a block, never worked around). `docs` holds
    what was collected before; the build adds the source's older records to them."""

    def __init__(self, reason: str, docs: list[Doc]) -> None:
        super().__init__(reason)
        self.docs = docs


@dataclass(frozen=True)
class Item:
    """One entry of a news list or feed."""

    url: str
    title: str
    published_at: str | None
    lead: str = ""


def make_doc(
    source: Source,
    *,
    url: str,
    title: str,
    text: str,
    published_at: str | None,
    retrieved_at: str,
    publisher: str | None = None,
    **fact_check,
) -> Doc | None:
    """Apply the storage policy of the source and build the record. None when there is no
    text, or for a job advert.

    `publisher` overrides the catalogue entry for aggregators that list several publishers.
    `fact_check` holds the optional fact-check fields of `Doc` (claim, rating, ...).
    """
    text = mask_personal(squash(text))
    title = mask_personal(" ".join(title.split()))
    if not text or not title or JOB_ADVERT.search(title):
        return None
    if fact_check.get("claim"):
        fact_check["claim"] = mask_personal(fact_check["claim"])
    if fact_check.get("rating"):
        fact_check["rating"] = mask_personal(fact_check["rating"])
    if source.storage == "excerpt":
        # A short fragment only; the document itself stays at `url`.
        text, _ = clip(text.replace("\n", " "), EXCERPT_CHARS)
        truncated = True
    else:
        text, truncated = clip(text, source.params.get("max_chars", MAX_TEXT_CHARS))
    # Mask again: the join of an excerpt's lines can make a number the first pass could not see.
    text = mask_personal(text)
    return Doc(
        id=doc_id(source.id, url),
        url=url,
        title=title,
        publisher=publisher or source.publisher,
        published_at=published_at,
        retrieved_at=retrieved_at,
        source_type=source.source_type,
        licence=source.licence,
        language=source.language,
        text=text,
        source_id=source.id,
        storage=source.storage,
        truncated=truncated,
        **fact_check,
    )


def moved_away(listed: str, fetched: str) -> bool:
    """A redirect to another registered domain: that site has its own terms and its own
    catalogue entry (or none), so the page is not taken under this source."""
    return registered_domain(listed) != registered_domain(fetched)


def items_to_docs(
    source: Source, client: PoliteClient, items: list[Item], listed_at: str
) -> list[Doc]:
    """Full-text sources: fetch every article. Excerpt sources: keep the lead from the list.

    A single failed page is skipped with a warning. When the site starts refusing us, we stop
    and keep what we have: a block is never retried or worked around.
    """
    docs: list[Doc] = []
    for item in items[: source.params.get("max_docs", len(items))]:
        if source.storage == "excerpt":
            doc = make_doc(
                source,
                url=item.url,
                title=item.title,
                text=item.lead or item.title,
                published_at=item.published_at,
                retrieved_at=listed_at,
            )
        else:
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
            doc = make_doc(
                source,
                url=page.url,
                title=item.title,
                text=main_text(page.text, page.url) or "",
                published_at=item.published_at,
                retrieved_at=page.fetched_at,
            )
        if doc is None:
            log.warning(
                "%s: nothing kept from %s (no text, or a job advert)",
                source.id,
                item.url,
            )
        else:
            docs.append(doc)
    return docs
