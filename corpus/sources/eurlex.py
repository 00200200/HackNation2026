"""EU legal acts by CELEX number, as published in the Official Journal.

The text comes from Cellar, the Publications Office's API for machines. The EUR-Lex website
answers scripted clients with a bot challenge, so it is only used as the address shown to people.
"""

import logging
import re

from corpus.catalog import Source
from corpus.extract import main_text, node_text, parse_html
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import Doc, parse_date
from corpus.sources.base import Stopped, make_doc

log = logging.getLogger("corpus")

CELLAR = "https://publications.europa.eu/resource/celex/{celex}"
EURLEX = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"
# Acts from before 2010 exist only as HTML, later ones as XHTML.
ACCEPT = "application/xhtml+xml, text/html;q=0.9"
OLD_TITLE = re.compile(
    r"((?:Rozporządzenie|Dyrektywa|Decyzja)\b.*?)\s*(?:\(Tekst mający znaczenie dla EOG\)|$)",
    re.DOTALL,
)


def act_header(html: str) -> tuple[str | None, str | None]:
    """(title, Official Journal date) of an act; None for what the page does not state."""
    root = parse_html(html)
    parts = (
        root.xpath(
            '//div[contains(@class, "eli-main-title")]//p[contains(@class, "doc-ti")]'
        )
        or root.xpath('//p[contains(@class, "doc-ti")]')[:3]
    )
    if parts:
        dates = root.xpath('//p[contains(@class, "hd-date")]')
        published = parse_date(node_text(dates[0])) if dates else None
        return " ".join(node_text(p) for p in parts), published
    # Older layout: the date sits in a Dublin Core tag, the title opens the text block.
    journal = "".join(root.xpath('//meta[@name="DC.source"]/@content'))
    date = re.search(r"(\d{2})/(\d{2})/(\d{4})", journal)
    block = next(
        (p for p in root.xpath('//div[@id="TexteOnly"]//p') if node_text(p)), None
    )
    # The title lines are nested paragraphs, so join the text nodes with spaces.
    opening = " ".join(" ".join(block.itertext()).split()) if block is not None else ""
    title = OLD_TITLE.match(opening)
    return (
        title.group(1) if title else None,
        parse_date(".".join(date.groups())) if date else None,
    )


def collect_eurlex(source: Source, client: PoliteClient) -> list[Doc]:
    """params: celex (list of CELEX numbers), max_chars."""
    headers = {"Accept": ACCEPT, "Accept-Language": source.language}
    docs: list[Doc] = []
    for celex in source.params["celex"]:
        try:
            page = client.get(
                CELLAR.format(celex=celex), headers=headers, max_age=source.max_age
            )
        except Blocked as exc:
            raise Stopped(str(exc), docs) from exc
        except FetchError as exc:
            log.warning("%s: skipped %s (%s)", source.id, celex, exc)
            continue
        title, published = act_header(page.text)
        doc = make_doc(
            source,
            url=EURLEX.format(lang=source.language.upper(), celex=celex),
            title=title or f"CELEX {celex}",
            text=main_text(page.text, page.url) or "",
            published_at=published,
            retrieved_at=page.fetched_at,
        )
        if doc is None:
            log.warning("%s: no text for %s", source.id, celex)
        else:
            docs.append(doc)
    return docs
