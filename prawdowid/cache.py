"""Source cache: every page fetched by web search, with publication and retrieval timestamps.

For now one local JSONL file (`corpus/docs.jsonl`, ignored by git: it holds full page text, which
we do not redistribute). `save_document` and `load_documents` are the only entry points, so the
Supabase store (#19) replaces this file without touching callers. The line format
(`url`, `text`, ...) is what `evals.run --corpus` reads for citation correctness.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from prawdowid.contract import Source

CACHE_PATH = Path(os.getenv("PRAWDOWID_CACHE") or "corpus/docs.jsonl")


class Document(BaseModel):
    url: str
    title: str
    publisher: str
    published_at: date
    fetched_at: datetime
    source_type: str
    domain: str
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
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [Document.model_validate_json(line) for line in f if line.strip()]


def save_document(doc: Document, path: Path = CACHE_PATH) -> bool:
    """Append the document unless its URL is cached already. True when it was added."""
    # ponytail: rereads the file on every save; fine for the demo corpus, #19 replaces it.
    if any(d.url == doc.url for d in load_documents(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(doc.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return True
