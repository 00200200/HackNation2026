"""Corpus record, domain helpers and JSONL I/O.

The field names `url` and `text` are read by `evals/run.py --corpus`; keep them.
"""

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import tldextract
from pydantic import BaseModel, field_validator

SourceType = Literal["official", "fact_checker", "incident_base"]
Storage = Literal["full_text", "excerpt"]

# The brief (section 5) asks for primary or official sources and for reliable secondary ones.
PRIMARY_TYPES = {"official"}
SECONDARY_TYPES = {"fact_checker", "incident_base"}

EXCERPT_CHARS = 500  # short fragment kept where there is no licence for the full text
MAX_TEXT_CHARS = 30_000  # default cap per document; keeps docs.jsonl far below 10 MB

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
EMAIL_MASK = "[adres e-mail usunięty]"

# Bundled Public Suffix List snapshot only: no network at import time. Private suffixes count
# too, so a blog on blogspot.com is its own domain, not the whole platform.
_PSL = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)


def registered_domain(url: str) -> str:
    """Registered domain by the Public Suffix List. gov.pl is a public suffix there, so
    www.gov.pl and sejm.gov.pl are different registered domains."""
    return _PSL(url).top_domain_under_public_suffix


def strict_domain(url: str) -> str:
    """Conservative count: every name under gov.pl is one domain."""
    domain = registered_domain(url)
    return "gov.pl" if domain.endswith(".gov.pl") else domain


def doc_id(source_id: str, url: str) -> str:
    return f"{source_id}-{hashlib.sha1(url.encode()).hexdigest()[:10]}"


def squash(text: str) -> str:
    """Collapse whitespace inside lines and drop empty lines."""
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Cut at a word boundary. Returns the text and whether anything was removed."""
    if len(text) <= limit:
        return text, False
    cut = text[:limit].rsplit(None, 1)[0].rstrip(" ,;:-")
    return cut + "…", True


def mask_emails(text: str) -> str:
    return EMAIL_RE.sub(EMAIL_MASK, text)


def parse_date(value: str | None) -> str | None:
    """Normalise `DD.MM.YYYY`, `DD-MM-YYYY` or an ISO date/datetime to ISO; None if unreadable."""
    if not value:
        return None
    value = value.strip()
    try:
        if m := re.fullmatch(r"(\d{1,2})[.-](\d{1,2})[.-](\d{4})", value):
            day, month, year = map(int, m.groups())
            return date(year, month, day).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value).isoformat()  # "Z" becomes "+00:00"
    except ValueError:
        return None


# Fact-check fields; left out of the JSON line when empty.
OPTIONAL_FIELDS = ("claim", "rating")


class Doc(BaseModel):
    id: str
    url: str
    title: str
    publisher: str
    published_at: str | None
    retrieved_at: str
    source_type: SourceType
    licence: str
    language: str
    text: str
    source_id: str  # catalogue entry this record came from
    storage: Storage
    # True when the text was cut (excerpt or size cap); the full text is at `url`.
    truncated: bool = False
    # Fact-checks only:
    claim: str | None = None  # the reviewed claim, verbatim
    rating: str | None = None  # the fact-checker's rating, verbatim

    @field_validator("id", "url", "title", "text", "publisher", "licence", "language")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def iso_date(cls, v: str | None) -> str | None:
        if v is not None and parse_date(v) != v:
            raise ValueError(f"not a normalised ISO date: {v!r}")
        return v


def write_jsonl(docs: list[Doc], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        json.dumps(
            d.model_dump(exclude={f for f in OPTIONAL_FIELDS if not getattr(d, f)}),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for d in sorted(docs, key=lambda d: d.id)
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[Doc]:
    with path.open(encoding="utf-8") as f:
        return [Doc.model_validate_json(line) for line in f if line.strip()]
