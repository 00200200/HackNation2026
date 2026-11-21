"""News lists rendered on the server (gov.pl, moje.cert.pl, Policja) and single pages.

Each parser turns one list page into items; the article text itself comes from trafilatura.
Dates are taken from the list, because the article pages carry no reliable date metadata.
"""

import logging
from collections.abc import Callable
from urllib.parse import urljoin

from corpus.catalog import Source
from corpus.extract import main_text, node_text, parse_html
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import Doc, parse_date
from corpus.sources.base import Item, Stopped, items_to_docs, make_doc, moved_away

log = logging.getLogger("corpus")

HAS_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " {} ")'


def _first(node, xpath: str):
    found = node.xpath(xpath)
    return found[0] if found else None


def parse_govpl(html: str, base_url: str) -> list[Item]:
    """`<div class="art-prev">` list of a gov.pl unit: date, title link and optional intro."""
    items = []
    for li in parse_html(html).xpath(f"//div[{HAS_CLASS.format('art-prev')}]//li"):
        link = _first(li, f".//div[{HAS_CLASS.format('title')}]//a[@href]")
        date = parse_date(node_text(_first(li, f".//span[{HAS_CLASS.format('date')}]")))
        if link is None or date is None:
            continue  # related-links blocks have no date; they are not news items
        items.append(
            Item(
                url=urljoin(base_url, link.get("href").strip()),
                title=node_text(link),
                published_at=date,
                lead=node_text(_first(li, f".//div[{HAS_CLASS.format('intro')}]")),
            )
        )
    return items


def parse_cert(html: str, base_url: str) -> list[Item]:
    """Advisory cards of moje.cert.pl/komunikaty/: title, lead and `DD-MM-YYYY [nr/year]`."""
    items = []
    for card in parse_html(html).xpath('//a[contains(@href, "/komunikaty/")][.//h2]'):
        date = None
        for cell in card.xpath(f".//div[{HAS_CLASS.format('subtitle')}]/div"):
            date = date or parse_date(node_text(cell))
        items.append(
            Item(
                url=urljoin(base_url, card.get("href").strip()),
                title=node_text(_first(card, ".//h2")),
                published_at=date,
                lead=node_text(_first(card, ".//p")),
            )
        )
    return items


def parse_policja(html: str, base_url: str) -> list[Item]:
    """`<li class="nnews">` list shared by policja.pl and the regional *.policja.gov.pl sites."""
    items = []
    for link in parse_html(html).xpath(f"//li[{HAS_CLASS.format('nnews')}]/a[@href]"):
        time = _first(link, ".//time[@datetime]")
        items.append(
            Item(
                url=urljoin(base_url, link.get("href").strip()),
                title=node_text(_first(link, ".//h3")),
                published_at=parse_date(time.get("datetime"))
                if time is not None
                else None,
                lead=node_text(_first(link, ".//p")),
            )
        )
    return items


def parse_gus(html: str, base_url: str) -> list[Item]:
    """Drupal news view of new.stat.gov.pl: `<article>` with `<time datetime>`, title, lead."""
    items = []
    for article in parse_html(html).xpath(
        "//li/article[.//time[@datetime]][.//h3//a[@href]]"
    ):
        link = _first(article, ".//h3//a[@href]")
        items.append(
            Item(
                url=urljoin(base_url, link.get("href").strip()),
                title=node_text(link),
                published_at=parse_date(
                    _first(article, ".//time[@datetime]").get("datetime")
                ),
                lead=node_text(
                    _first(
                        article,
                        f".//div[{HAS_CLASS.format('views-field-field-article-lead')}]",
                    )
                ),
            )
        )
    return items


PARSERS: dict[str, Callable[[str, str], list[Item]]] = {
    "govpl": parse_govpl,
    "cert": parse_cert,
    "policja": parse_policja,
    "gus": parse_gus,
}


def collect_news_list(source: Source, client: PoliteClient) -> list[Doc]:
    """params: list_url (with `{page}`), parser, first_page, pages, max_docs."""
    params = source.params
    parse = PARSERS[params["parser"]]
    first = params.get("first_page", 1)
    items: dict[str, Item] = {}
    listed_at = ""
    for number in range(first, first + params.get("pages", 1)):
        try:
            page = client.get(
                params["list_url"].format(page=number), max_age=source.max_age
            )
        except Blocked:
            raise  # the site refuses us: no more list pages and no articles either
        except FetchError as exc:
            if not items:
                raise  # the first list page decides whether the source works at all
            log.warning(
                "%s: list page %d failed (%s), keeping earlier pages",
                source.id,
                number,
                exc,
            )
            break
        listed_at = listed_at or page.fetched_at
        for item in parse(page.text, page.url):
            # Lists sometimes link to other sites; those have their own terms and entries.
            if item.title and not moved_away(params["list_url"], item.url):
                items.setdefault(item.url, item)
    if not items:
        raise FetchError("the list page has no items: the page layout may have changed")
    return items_to_docs(source, client, list(items.values()), listed_at)


def page_title(html: str) -> str:
    """Heading of the main content; falls back to `<title>` without the site suffix."""
    root = parse_html(html)
    for xpath in ('//article[@id="main-content"]//h2', "//main//h1", "//h1"):
        if title := node_text(_first(root, xpath)):
            return title
    return node_text(_first(root, "//title")).split(" - ")[0]


def collect_pages(source: Source, client: PoliteClient) -> list[Doc]:
    """Single pages listed in params.urls. They carry no reliable date: published_at is null."""
    docs: list[Doc] = []
    for url in source.params["urls"]:
        try:
            page = client.get(url, max_age=source.max_age)
        except Blocked as exc:
            raise Stopped(str(exc), docs) from exc
        except FetchError as exc:
            log.warning("%s: skipped %s (%s)", source.id, url, exc)
            continue
        if moved_away(url, page.url):
            log.warning("%s: skipped %s (redirects to %s)", source.id, url, page.url)
            continue
        doc = make_doc(
            source,
            url=page.url,
            title=page_title(page.text),
            text=main_text(page.text, page.url) or "",
            published_at=None,
            retrieved_at=page.fetched_at,
        )
        if doc is None:
            log.warning("%s: no text in %s", source.id, url)
        else:
            docs.append(doc)
    return docs
