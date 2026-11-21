"""Source cache: the pages web search read, with publication and retrieval timestamps.

What is kept (brief: no archiving of full content without a legal basis, licence, retention,
access control and deletion):
- Metadata of every page: URL, title, publisher, dates, source type, domain, licence.
- Full text only when the domain's licence is confirmed (`Domain.licence` in websearch.py).
  Today none is, so `text` is stored empty. The pipeline still uses the live text in memory.
- Retention: records older than `RETENTION_DAYS` (by `fetched_at`) are dropped on every save;
  `delete_document(url)` removes one record, deleting the file removes everything.
- Access: one local JSONL file, owner read/write only (0600), ignored by git.
- A URL keeps one record: the latest fetch replaces the older one.

`save_document`, `load_documents` and `delete_document` are the only entry points, so the
Supabase store (#19) replaces this file without touching callers. The line format
(`url`, `text`, ...) is what `evals.run --corpus` reads.
"""

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from prawdowid.contract import Source

CACHE_PATH = Path(os.getenv("PRAWDOWID_CACHE") or "corpus/docs.jsonl")
RETENTION_DAYS = 30


class Document(BaseModel):
    url: str
    title: str
    publisher: str
    published_at: date
    fetched_at: datetime
    source_type: str
    domain: str
    licence: str | None = None
    text: str

    def to_source(self, fragment: str | None = None) -> Source:
        return Source(
            title=self.title,
            publisher=self.publisher,
            published_at=self.published_at,
            fetched_at=self.fetched_at,
            url=self.url,
            source_type=self.source_type,
            fragment=fragment,
        )


def load_documents(path: Path = CACHE_PATH) -> list[Document]:
    """Records within retention. Expired ones are never returned, even before the next save."""
    if not path.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    with path.open(encoding="utf-8") as f:
        docs = [Document.model_validate_json(line) for line in f if line.strip()]
    return [d for d in docs if d.fetched_at >= cutoff]


def save_document(doc: Document, path: Path = CACHE_PATH) -> None:
    """Store the latest fetch of this URL (text only if licensed) and drop expired records."""
    kept = [d for d in load_documents(path) if d.url != doc.url]
    _write(path, [*kept, doc])


def delete_document(url: str, path: Path = CACHE_PATH) -> bool:
    """Remove the record of this URL. True when there was one."""
    docs = load_documents(path)
    kept = [d for d in docs if d.url != url]
    _write(path, kept)
    return len(kept) < len(docs)


def _write(path: Path, docs: list[Document]) -> None:
    """Rewrite the file. Text of unlicensed records is dropped here, old records included."""
    # ponytail: whole-file rewrite, one writer process at a time (two concurrent savers can
    # lose a record). Fine for the demo corpus; the Supabase store (#19) replaces it.
    docs = [d if d.licence else d.model_copy(update={"text": ""}) for d in docs]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(d.model_dump_json() + "\n" for d in docs)
    tmp.replace(path)
