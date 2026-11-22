"""Text extraction for one fetched page, run as a separate process that the caller can kill.

Usage: python -I extract_worker.py <content-type> <url>, page bytes on stdin, one JSON object on
stdout: {"kind": "ok", "text", "title", "publisher", "date", "hidden"} or {"kind": "paywall" | "no_text"}.
"paywall" covers schema.org paywall markup (JSON-LD or microdata) and inline sign-in or subscribe
walls, in the article text or in a form. "hidden" is the text of the channels the extractor drops
(HTML comments, img alt, display:none or hidden nodes): never shown to a model, only screened.
Self-contained on purpose (no prawdowid imports), so it runs with -I.

Work is bounded twice: the caller kills the process at its deadline, and the parsers stop after a
fixed budget (pages, decompressed bytes, characters), so even an unkilled run has a ceiling.
"""

import json
import re
import sys
from io import BytesIO

PDF_TYPE = "application/pdf"
# Ceilings for one page. Text beyond MAX_TEXT_CHARS is never needed: the verifier reads 5000.
MAX_TEXT_CHARS = 20_000
MAX_META_CHARS = 300
MAX_PDF_PAGES = 50
MAX_DECOMPRESSED_BYTES = (
    20_000_000  # per stream and per decode, vs. pypdf's 75 MB default
)
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
MAX_CPU_S = 15
# An inline access wall: a notice that the rest needs a login or subscription. It must say why
# ("..., aby przeczytać"), so an article quoting a scam's "zaloguj się na stronie" is still read.
# ponytail: fixed phrase list, Polish and English; extend when a real wall slips through.
WALL_NOTICE = re.compile(
    r"(zaloguj się|zarejestruj się|wykup (subskrypcję|prenumeratę|dostęp)|kup (subskrypcję|dostęp))"
    r",? (aby|by|żeby) (przeczytać|czytać|kontynuować|zobaczyć|uzyskać|mieć)"
    r"|(dostępn[ya]|zarezerwowan[ya]) (tylko |wyłącznie )?dla (subskrybentów|prenumeratorów|zalogowanych)"
    r"|(sign|log) in to (read|continue|view)|subscribe to (read|continue)"
    r"|(article|content|story) is (only )?(available )?(for|to) subscribers",
    re.IGNORECASE,
)
PASSWORD_INPUT = re.compile(rb"<input[^>]+type\s*=\s*[\"']?password", re.IGNORECASE)
# A password form beside this much text or less is a preview behind a login, not a full article.
# ponytail: one length cut; a site with a login box in the header and a short note is refused.
PREVIEW_CHARS = 1500


def limit_process() -> None:
    import resource

    for limit, value in (
        (resource.RLIMIT_AS, MAX_MEMORY_BYTES),
        (resource.RLIMIT_CPU, MAX_CPU_S),
    ):
        try:
            resource.setrlimit(limit, (value, value))
        except (
            ValueError,
            OSError,
        ):  # macOS rejects RLIMIT_AS; the deadline kill still holds
            pass


def is_paywalled(html: bytes) -> bool:
    """schema.org marks paywalled articles with isAccessibleForFree: false in JSON-LD."""
    for raw in re.findall(
        rb"<script[^>]+application/ld\+json[^>]*>(.*?)</script>",
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if str(item.get("isAccessibleForFree", "")).lower() == "false":
                    return True
                stack.extend(item.values())
    return False


def extract_pdf(body: bytes) -> dict:
    from pypdf import PdfReader, apply_configuration

    try:
        with apply_configuration(
            maximum_declared_stream_length=MAX_DECOMPRESSED_BYTES,
            array_based_stream_maximum_output_length=MAX_DECOMPRESSED_BYTES,
            zlib_maximum_output_length=MAX_DECOMPRESSED_BYTES,
            lzw_maximum_output_length=MAX_DECOMPRESSED_BYTES,
            run_length_maximum_output_length=MAX_DECOMPRESSED_BYTES,
            brotli_maximum_output_length=MAX_DECOMPRESSED_BYTES,
        ):
            reader = PdfReader(BytesIO(body))
            parts, size = [], 0
            for n, page in enumerate(reader.pages):
                if n >= MAX_PDF_PAGES or size >= MAX_TEXT_CHARS:
                    break
                part = page.extract_text() or ""
                parts.append(part)
                size += len(part)
            title = reader.metadata.title if reader.metadata else None
    # pypdf raises many types on a malformed or over-limit file; any of them means no text.
    except Exception:  # noqa: BLE001
        return {"kind": "no_text"}
    return ok("\n".join(parts), title and str(title), None, None)


def paywalled_microdata(tree) -> bool:
    """schema.org microdata form of the paywall marker: itemprop="isAccessibleForFree" false."""
    return any(
        (el.get("content") or el.text_content()).strip().lower() == "false"
        for el in tree.xpath('//*[@itemprop="isAccessibleForFree"]')
    )


def extract_html(body: bytes, url: str) -> dict:
    import trafilatura
    from trafilatura.utils import load_html

    tree = load_html(body)  # decodes like trafilatura does, so Polish notices match
    if tree is None:
        return {"kind": "no_text"}
    if is_paywalled(body) or paywalled_microdata(tree):
        return {"kind": "paywall"}
    # trafilatura drops small forms from its text, so a notice inside one is read from the HTML.
    # Like a password form, it marks a wall only beside a preview: a newsletter box saying
    # "subscribe to read our digest" must not refuse a full free article.
    form_notice = any(WALL_NOTICE.search(f.text_content()) for f in tree.iter("form"))
    hidden = hidden_text(body)
    doc = trafilatura.bare_extraction(
        tree, url=url, with_metadata=True, include_comments=False
    )
    if not doc:
        return {"kind": "no_text"}
    text = doc.text or ""
    if WALL_NOTICE.search(text) or (
        (PASSWORD_INPUT.search(body) or form_notice) and len(text) < PREVIEW_CHARS
    ):
        return {"kind": "paywall"}
    return ok(doc.text, doc.title, doc.sitename, doc.date, hidden)


def hidden_text(body: bytes) -> str:
    """Text a reader never sees and the extractor drops: comments, img alt, display:none nodes.

    Parsed again with comments kept (trafilatura's loader removes them).
    """
    from lxml import etree, html
    from trafilatura.utils import decode_file

    parser = html.HTMLParser(remove_comments=False)
    try:
        # Decoded as `extract_html` decodes it: lxml guesses the encoding of raw bytes without a
        # declaration, and a Polish comment would reach `screen` garbled.
        try:
            tree = html.fromstring(decode_file(body), parser=parser)
        except ValueError:
            # A str with an XML encoding declaration is refused; the raw bytes are not.
            tree = html.fromstring(body, parser=parser)
    except (ValueError, etree.ParserError):
        return ""
    parts = [c.text or "" for c in tree.xpath("//comment()")]
    parts += tree.xpath("//img/@alt")
    for node in tree.xpath("//*[@hidden or @style]"):
        style = (node.get("style") or "").replace(" ", "").lower()
        if node.get("hidden") is not None or "display:none" in style:
            parts.append(node.text_content())
    return "\n".join(p.strip() for p in parts if p.strip())[:MAX_TEXT_CHARS]


def ok(text, title, publisher, date, hidden="") -> dict:
    return {
        "kind": "ok",
        "text": (text or "").strip()[:MAX_TEXT_CHARS],
        "title": (title or "").strip()[:MAX_META_CHARS] or None,
        "publisher": (publisher or "").strip()[:MAX_META_CHARS] or None,
        "date": date,
        "hidden": hidden,
    }


def main() -> None:
    limit_process()
    ctype, url = sys.argv[1], sys.argv[2]
    body = sys.stdin.buffer.read()
    result = extract_pdf(body) if ctype == PDF_TYPE else extract_html(body, url)
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
