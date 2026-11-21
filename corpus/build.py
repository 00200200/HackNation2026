"""Rebuild the evidence corpus from the source catalogue.

Usage: uv run python -m corpus.build [--refresh] [--only SOURCE_ID ...] [--force]

Reads `corpus/catalog.yaml`, runs the collector of every active source and writes
`corpus/evidence.jsonl` (the corpus) and `corpus/manifest.json` (what was collected, skipped and
why). Pages are cached in `corpus/.cache/`: lists, feeds and API answers are fetched again once
they are older than the source's update interval, article pages are reused until `--refresh`.
`--only` rebuilds the named sources and keeps the rest of the existing file. A source that fails,
stops part way, returns nothing or misses its key keeps its records from the previous build
(except snapshots such as live warnings), and the manifest says so. When the result misses the
thresholds of `corpus.check`, nothing is written (exit code 1) unless `--force` is given.
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from corpus.catalog import Catalog, Source, load_catalog
from corpus.check import DOCS_PATH, problems, summarize
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import Doc, read_jsonl, write_jsonl
from corpus.sources import COLLECTORS
from corpus.sources.base import Stopped

log = logging.getLogger("corpus")

ROOT = Path(__file__).parent
CACHE_DIR = ROOT / ".cache"
MANIFEST_PATH = ROOT / "manifest.json"
WORKERS = 8  # sources run side by side; the client still spaces requests per domain
INCOMPLETE = (
    "stopped",
    "blocked",
    "failed",
    "skipped",
    "no documents",
)  # not a full run


class SourceWarnings(logging.Handler):
    """Collects the warnings of each source (collectors log them as "<source id>: ...")."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.by_source: dict[str, list[str]] = defaultdict(list)

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        source_id, _, rest = message.partition(": ")
        if rest:
            self.by_source[source_id].append(rest)


def run_source(source: Source, client: PoliteClient) -> tuple[list[Doc], str]:
    """Collect one source. Returns its documents and a note for the report ("" when fine)."""
    if source.requires_env and not os.environ.get(source.requires_env):
        return [], f"skipped: {source.requires_env} is not set"
    try:
        docs = COLLECTORS[source.collector](source, client)
    except Stopped as exc:  # stopped part way: keep what was collected before
        return exc.docs, f"stopped after {len(exc.docs)} records: {exc}"
    except Blocked as exc:
        return [], f"blocked: {exc}"
    except FetchError as exc:
        return [], f"failed: {exc}"
    except Exception as exc:  # one broken source must not stop the others
        log.exception("%s: collector crashed", source.id)
        return [], f"failed: {type(exc).__name__}: {exc}"
    return docs, "" if docs else "no documents"


def build(
    catalog: Catalog,
    client: PoliteClient,
    only: set[str] | None = None,
    previous: list[Doc] | None = None,
) -> tuple[list[Doc], list[dict]]:
    """Run the active sources (or just `only`). Sources that are not run, or that fail, keep
    their records from `previous`. Returns the documents and one report row per entry."""
    previous = previous or []
    active = [s for s in catalog.sources if s.status == "active"]
    selected = [s for s in active if only is None or s.id in only]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = dict(
            zip(
                (s.id for s in selected),
                pool.map(lambda s: run_source(s, client), selected),
                strict=True,
            )
        )
    removed = {r.url for r in catalog.removed_urls}
    active_ids = {s.id for s in active}
    docs: dict[str, Doc] = {}
    rows = []
    for source in catalog.sources:
        row = {
            "id": source.id,
            "domain": source.domain,
            "registered_domain": source.registered_domain,
            "source_type": source.source_type,
            "status": source.status,
            "documents": 0,
            "note": source.excluded_reason or source.note or "",
        }
        collected: list[Doc] = []
        if source.id in active_ids:
            old = [d for d in previous if d.source_id == source.id]
            collected, note = results.get(source.id, ([], ""))
            if source.id not in results:
                collected, note = old, "not rebuilt, kept from the previous build"
            elif note.startswith(INCOMPLETE) and not source.params.get("snapshot"):
                # Fill the gap with the older records; a snapshot (live warnings) is not kept.
                seen = {d.url for d in collected}
                older = [d for d in old if d.url not in seen]
                collected = collected + older
                if older:
                    note = f"{note}; kept {len(older)} records from the previous build"
            row["note"] = note
        for doc in collected:
            if doc.url in removed:
                continue
            if doc.url in docs:  # the first catalogue entry that has a URL keeps it
                log.info(
                    "%s: %s is already in %s",
                    source.id,
                    doc.url,
                    docs[doc.url].source_id,
                )
                continue
            docs[doc.url] = doc
            row["documents"] += 1
        rows.append(row)
    return list(docs.values()), rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--refresh", action="store_true", help="ignore the page cache")
    parser.add_argument(
        "--only", nargs="+", metavar="SOURCE_ID", help="rebuild only these"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="write the result even if it misses a threshold",
    )
    parser.add_argument("--out", type=Path, default=DOCS_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr
    )
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    warnings = SourceWarnings()
    log.addHandler(warnings)

    catalog = load_catalog()
    only = set(args.only) if args.only else None
    if only and (
        unknown := only - {s.id for s in catalog.sources if s.status == "active"}
    ):
        parser.error(f"not an active source: {', '.join(sorted(unknown))}")
    previous = read_jsonl(args.out) if args.out.exists() else []
    client = PoliteClient(cache_dir=CACHE_DIR, refresh=args.refresh)
    docs, rows = build(catalog, client, only, previous)
    for row in rows:
        if found_warnings := warnings.by_source.get(row["id"]):
            row["warnings"] = len(found_warnings)
            row["first_warnings"] = found_warnings[:3]

    draft = args.out.with_suffix(".draft.jsonl")
    write_jsonl(docs, draft)
    size = draft.stat().st_size
    found = problems(docs, size)
    for row in rows:
        if row["status"] == "active":
            extra = f" ({row['warnings']} warnings)" if row.get("warnings") else ""
            print(f"{row['documents']:5d}  {row['id']:24} {row['note']}{extra}")
    summary = summarize(docs)
    print(
        f"{len(docs)} documents, {len(summary['registered_domains'])} registered domains "
        f"({len(summary['strict_domains'])} with *.gov.pl as one), "
        f"types {summary['source_types']}, {size / 1e6:.2f} MB"
    )
    for problem in found:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if found and not args.force:
        draft.unlink()
        print(f"Not written: {args.out} is unchanged (use --force to write anyway).")
        return 1

    os.replace(draft, args.out)
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "command": "uv run python -m corpus.build"
                + (f" --only {' '.join(sorted(only))}" if only else ""),
                "size_bytes": size,
                "summary": summary,
                "problems": found,
                "sources": rows,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Written: {args.out} and {MANIFEST_PATH}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
