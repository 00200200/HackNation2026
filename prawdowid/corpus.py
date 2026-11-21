"""Build (seed) the demo corpus: run the seed queries through web search on each allowlisted domain.

    uv run python -m prawdowid.corpus [--target 120]

Pages go to the PostgreSQL store (`prawdowid/cache.py`) when `DATABASE_URL` is set, else to the
local JSONL cache. This script is the only writer of the database; checks never write to it. With the database, expired pages are deleted first (retention).
`corpus/manifest.jsonl` (committed) lists every stored document without its text (url, publisher,
domain, type, licence, dates), so the source list stays auditable. Page text from the database is
never exported: retention and deletion in the database cover every stored copy.
"""

import argparse
import asyncio
import json
import logging
import os
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from prawdowid.cache import (
    DATABASE_ENV,
    delete_expired,
    load_documents,
    store_document,
    stored_documents,
)
from prawdowid.websearch import ALLOWLIST, search_web

MANIFEST = Path("corpus/manifest.jsonl")
# Seed queries, one per line; "#" starts a comment. Committed so the seed is reproducible.
QUERIES = Path("corpus/queries.txt")


def queries(path: Path = QUERIES) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def local_database_url() -> str:
    """URI of the compose `db` service from the same settings compose reads (.env)."""
    password = quote(os.getenv("POSTGRES_PASSWORD") or "prawdowid", safe="")
    port = os.getenv("DB_PORT") or "5433"
    return f"postgresql://prawdowid:{password}@127.0.0.1:{port}/prawdowid"


def _use_database() -> bool:
    return bool(os.getenv(DATABASE_ENV))


async def build(target: int) -> None:
    documents = stored_documents if _use_database() else load_documents
    for topic in queries():
        for domain in ALLOWLIST:
            if len(documents()) >= target:
                return
            # The seed is the only writer of the database: search itself saves only to JSONL.
            result = await search_web(
                topic, domains=[domain], limit=5, save=not _use_database()
            )
            if _use_database():
                for d in result.documents:
                    await asyncio.to_thread(store_document, d)
            print(f"{domain:22} {topic:32} {len(result.documents)} docs")


def write_manifest() -> None:
    # Metadata only: page text stays in the database, under its retention and deletion.
    docs = stored_documents() if _use_database() else load_documents()
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
    parser.add_argument(
        "--local-db",
        action="store_true",
        help="seed the compose db service unless DATABASE_URL is set",
    )
    args = parser.parse_args()
    if args.local_db and not os.getenv(DATABASE_ENV):
        os.environ[DATABASE_ENV] = local_database_url()
    logging.basicConfig(level=logging.WARNING)
    if _use_database():
        print(f"retention: {delete_expired()} expired documents deleted")
    asyncio.run(build(args.target))
    write_manifest()
