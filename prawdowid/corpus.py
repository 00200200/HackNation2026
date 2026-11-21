"""Build the demo corpus: run seed topics through web search on each allowlisted domain.

    uv run python -m prawdowid.corpus [--target 120]

Pages go to the source cache (`prawdowid/cache.py`). `corpus/manifest.jsonl` (committed) lists
every cached document without its text, so the source list stays auditable.
"""

import argparse
import asyncio
import json
import logging
from collections import Counter
from pathlib import Path

from prawdowid.cache import load_documents
from prawdowid.websearch import ALLOWLIST, search_web

MANIFEST = Path("corpus/manifest.jsonl")
# Topics the MSZ brief names: disinformation about Poland, the EU, the war in Ukraine, elections,
# health and the economy. Not eval cases.
TOPICS = [
    "dezinformacja",
    "wojna w Ukrainie",
    "sankcje wobec Rosji",
    "wybory",
    "szczepienia",
    "inflacja",
    "uchodźcy z Ukrainy",
    "NATO wschodnia flanka",
    "Unia Europejska budżet",
    "migracja granica z Białorusią",
]


async def build(target: int) -> None:
    for topic in TOPICS:
        for domain in ALLOWLIST:
            if len(load_documents()) >= target:
                return
            result = await search_web(topic, domains=[domain], limit=5)
            print(f"{domain:22} {topic:32} {len(result.documents)} docs")


def write_manifest() -> None:
    docs = load_documents()
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
    asyncio.run(build(parser.parse_args().target))
    write_manifest()
