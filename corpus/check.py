"""Counts and requirement checks for the corpus file.

Usage: uv run python -m corpus.check [corpus/evidence.jsonl]
Thresholds come from the task brief, section 5: at least 100 documents or records, 10 domains
and two source types (primary or official plus reliable secondary).
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from corpus.schema import (
    EMAIL_RE,
    EXCERPT_CHARS,
    PRIMARY_TYPES,
    SECONDARY_TYPES,
    Doc,
    read_jsonl,
    registered_domain,
    strict_domain,
)

DOCS_PATH = Path(__file__).parent / "evidence.jsonl"
DISINFO_PATH = (
    Path(__file__).parent / "disinfo_domains.json"
)  # written with the EUvsDisinfo token
CONTACT_PERSONS = re.compile(r"(?i)osob[ay] do kontaktu|osoba kontaktowa")
MIN_DOCS = 100
MIN_DOMAINS = 10
MAX_BYTES = 10 * 1024 * 1024  # the pre-push hook refuses bigger files
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def looks_like_pesel(digits: str) -> bool:
    """11 digits with a valid PESEL month, day and check digit."""
    month, day = int(digits[2:4]) % 20, int(digits[4:6])
    checksum = sum(int(d) * w for d, w in zip(digits, PESEL_WEIGHTS, strict=False))
    return (
        1 <= month <= 12
        and 1 <= day <= 31
        and (10 - checksum % 10) % 10 == int(digits[10])
    )


def summarize(docs: list[Doc]) -> dict:
    return {
        "documents": len(docs),
        "registered_domains": dict(
            Counter(registered_domain(d.url) for d in docs).most_common()
        ),
        "strict_domains": dict(
            Counter(strict_domain(d.url) for d in docs).most_common()
        ),
        "source_types": dict(Counter(d.source_type for d in docs).most_common()),
        "storage": dict(Counter(d.storage for d in docs).most_common()),
        "sources": dict(Counter(d.source_id for d in docs).most_common()),
        "without_published_at": sum(d.published_at is None for d in docs),
    }


def disinfo_domains(path: Path = DISINFO_PATH) -> set[str]:
    """Domains linked in EUvsDisinfo cases; empty until the list has been built."""
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")).get("domains", {}))


def problems(
    docs: list[Doc], size_bytes: int | None = None, banned: set[str] | None = None
) -> list[str]:
    """Everything that breaks a requirement; an empty list means the corpus passes.
    `banned` holds domains known for disinformation: they are never evidence."""
    found = []
    banned = disinfo_domains() if banned is None else banned
    summary = summarize(docs)
    if summary["documents"] < MIN_DOCS:
        found.append(f"{summary['documents']} documents, need at least {MIN_DOCS}")
    if len(summary["registered_domains"]) < MIN_DOMAINS:
        found.append(
            f"{len(summary['registered_domains'])} registered domains, need at least {MIN_DOMAINS}"
        )
    types = set(summary["source_types"])
    if not types & PRIMARY_TYPES:
        found.append("no primary or official source")
    if not types & SECONDARY_TYPES:
        found.append("no reliable secondary source (fact-checker or incident base)")
    if size_bytes is not None and size_bytes >= MAX_BYTES:
        found.append(f"file has {size_bytes} bytes, the push limit is {MAX_BYTES}")
    for field in ("id", "url"):
        repeated = [
            v for v, n in Counter(getattr(d, field) for d in docs).items() if n > 1
        ]
        if repeated:
            found.append(f"{len(repeated)} repeated {field} values, e.g. {repeated[0]}")
    for doc in docs:
        if doc.storage == "excerpt" and len(doc.text) > EXCERPT_CHARS + 1:
            found.append(f"{doc.id}: excerpt has {len(doc.text)} characters")
        fields = [doc.text, doc.title, doc.claim or "", doc.claim_author or ""]
        fields += [doc.claim_source or ""] + [link.text for link in doc.cited_links]
        if any(EMAIL_RE.search(value) for value in fields):
            found.append(f"{doc.id}: e-mail address in the text")
        if any(
            looks_like_pesel(n) for n in re.findall(r"(?<!\d)\d{11}(?!\d)", doc.text)
        ):
            found.append(f"{doc.id}: a number that looks like a PESEL")
        if CONTACT_PERSONS.search(doc.text):
            found.append(f"{doc.id}: names contact persons")
        if registered_domain(doc.url) in banned:
            found.append(f"{doc.id}: from a domain on the disinformation list")
    return found


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DOCS_PATH
    if not path.exists():
        print(
            f"{path} does not exist: run `uv run python -m corpus.build`",
            file=sys.stderr,
        )
        return 1
    docs = read_jsonl(path)
    summary = summarize(docs)
    size = path.stat().st_size
    print(f"{path}: {summary['documents']} documents, {size / 1e6:.2f} MB")
    print(f"registered domains ({len(summary['registered_domains'])}):")
    for domain, count in summary["registered_domains"].items():
        print(f"  {count:5d}  {domain}")
    strict = summary["strict_domains"]
    print(
        f"domains with every *.gov.pl counted as one ({len(strict)}): {', '.join(strict)}"
    )
    print(f"source types: {summary['source_types']}")
    print(f"storage: {summary['storage']}")
    print(f"without a publication date: {summary['without_published_at']}")
    found = problems(docs, size)
    for problem in found:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    print("FAIL" if found else "OK: the corpus meets the brief's thresholds")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
