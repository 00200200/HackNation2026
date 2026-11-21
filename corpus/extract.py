"""HTML to clean text (trafilatura) and small markup helpers (lxml)."""

import re

import lxml.html
from trafilatura import extract, html2txt


def main_text(html: str, url: str) -> str | None:
    """Main text of a page without navigation, footer or comments; None when none was found."""
    text = extract(html, url=url, include_comments=False, include_tables=True)
    return text.strip() if text and text.strip() else None


def all_text(html: str) -> str | None:
    """All text of a document that has no site chrome, such as a legal act served on its own.
    `main_text` would keep only the block it takes for the article (for Sejm acts: footnotes)."""
    text = html2txt(html)
    return text.strip() if text and text.strip() else None


def parse_html(html: str) -> lxml.html.HtmlElement:
    # lxml refuses a str that still carries an XML encoding declaration (EUR-Lex pages do),
    # and an empty document.
    markup = re.sub(r"^\s*<\?xml[^>]*\?>", "", html).strip()
    return lxml.html.fromstring(markup or "<html></html>")


def plain_text(markup: str | None) -> str:
    """Text of an HTML snippet (feed summaries, list items) on one line."""
    if not markup or not markup.strip():
        return ""
    return " ".join(lxml.html.fromstring(f"<div>{markup}</div>").text_content().split())


def node_text(node: lxml.html.HtmlElement | None) -> str:
    """Text of an element on one line; a `<br>` counts as a space."""
    if node is None:
        return ""
    for br in node.iter("br"):
        br.tail = f" {br.tail or ''}"
    return " ".join(node.text_content().split())
