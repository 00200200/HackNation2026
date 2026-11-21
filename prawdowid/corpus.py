"""Build (seed) the demo corpus: run the seed queries through web search on each allowlisted domain.

    uv run python -m prawdowid.corpus [--target 120]

Pages go to the source cache (`prawdowid/cache.py`): the Supabase database when `DATABASE_URL` is
set, else the local JSONL file. With the database, expired pages are deleted first (retention).
`corpus/manifest.jsonl` (committed) lists every stored document without its text (url, publisher,
domain, type, licence, dates), so the source list stays auditable. With the database it also
exports the full text to `corpus/docs.jsonl` for `evals.run --corpus`.
"""

import argparse
import asyncio
import json
import logging
import os
from collections import Counter
from pathlib import Path

from prawdowid.cache import CACHE_PATH, DATABASE_ENV, delete_expired, load_documents
from prawdowid.websearch import ALLOWLIST, search_web

MANIFEST = Path("corpus/manifest.jsonl")
# Seed queries, one per line; "#" starts a comment. Committed so the seed is reproducible.
QUERIES = Path("corpus/queries.txt")


def queries(path: Path = QUERIES) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


async def build(target: int) -> None:
    for topic in queries():
        for domain in ALLOWLIST:
            if len(load_documents()) >= target:
                return
            result = await search_web(topic, domains=[domain], limit=5)
            print(f"{domain:22} {topic:32} {len(result.documents)} docs")


def write_manifest() -> None:
    docs = load_documents()
    if os.getenv(DATABASE_ENV):
        # Full-text export of the database for `evals.run --corpus` (ignored by git).
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_PATH.open("w", encoding="utf-8") as f:
            for d in docs:
                f.write(
                    json.dumps(d.model_dump(mode="json"), ensure_ascii=False) + "\n"
                )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8") as f:
        for d in docs:
            row = d.model_dump(mode="json", exclude={"text"})
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    types = Counter(d.source_type for d in docs)
    print(
        f"{len(docs)} documents, {len({d.domain for d in docs})} hosts, "
        f"{len({d.publisher for d in docs})} publishers, types {dict(types)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=120)
    logging.basicConfig(level=logging.WARNING)
    if os.getenv(DATABASE_ENV):
        print(f"retention: {delete_expired()} expired documents deleted")
    asyncio.run(build(parser.parse_args().target))
    write_manifest()
