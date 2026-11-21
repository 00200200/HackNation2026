"""Text extraction for one fetched page, run as a separate process that the caller can kill.

Usage: python -I extract_worker.py <content-type> <url>, page bytes on stdin, one JSON object on
stdout: {"kind": "ok", "text", "title", "publisher", "date"} or {"kind": "paywall" | "no_text"}.
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


def extract_html(body: bytes, url: str) -> dict:
    import trafilatura

    if is_paywalled(body):
        return {"kind": "paywall"}
    doc = trafilatura.bare_extraction(
        body, url=url, with_metadata=True, include_comments=False
    )
    if not doc:
        return {"kind": "no_text"}
    return ok(doc.text, doc.title, doc.sitename, doc.date)


def ok(text, title, publisher, date) -> dict:
    return {
        "kind": "ok",
        "text": (text or "").strip()[:MAX_TEXT_CHARS],
        "title": (title or "").strip()[:MAX_META_CHARS] or None,
        "publisher": (publisher or "").strip()[:MAX_META_CHARS] or None,
        "date": date,
    }


def main() -> None:
    limit_process()
    ctype, url = sys.argv[1], sys.argv[2]
    body = sys.stdin.buffer.read()
    result = extract_pdf(body) if ctype == PDF_TYPE else extract_html(body, url)
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
