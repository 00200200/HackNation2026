"""Runs the Prawdowid eval and writes results.

Usage: uv run python -m evals.run [--quick] [--cases evals/cases.jsonl] [--corpus corpus/docs.jsonl]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from evals import adapter, metrics

REQUIRED_SCENARIOS = ("A", "B", "C", "D", "E", "G", "I", "J")
NON_PRODUCT = (
    "docs/",
    ".claude/",
    ".githooks/",
    ".github/",
    "evals/cases",
    "evals/results/",
)
NON_PRODUCT_FILES = (".gitignore", "LICENSE")


def git(*args: str) -> str:
    # rstrip only: porcelain status lines start with a meaningful space
    return subprocess.run(
        ["git", *args], check=False, capture_output=True, text=True
    ).stdout.rstrip("\n")


def load_jsonl(path: str) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def is_product(path: str) -> bool:
    return not (
        path.endswith(".md")
        or path.startswith(NON_PRODUCT)
        or path.startswith(NON_PRODUCT_FILES)
    )


def call(case: dict, channel: str) -> dict:
    adapter.wait_turn()  # rate limit; not counted as latency
    start = time.monotonic()
    try:
        response, error = adapter.ask(case["input"], channel), None
    except (
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:  # network, HTTP, bad JSON, missing URL
        response, error = {"status": "technical_error"}, f"{type(exc).__name__}: {exc}"
    return {
        "channel": channel,
        "response": response,
        "seconds": time.monotonic() - start,
        "error": error,
    }


def signature(response: dict) -> tuple:
    claim = metrics.main_claim(response) or {}
    urls = sorted(e.get("url", "") for e in claim.get("evidence") or [])
    return metrics.predicted_verdict(response), tuple(urls)


def evaluate(
    cases: list[dict], corpus: dict[str, str] | None
) -> tuple[dict, list[dict]]:
    rows = []
    for case in cases:
        channels = [
            ch for ch in case.get("channels") or ["web"] if adapter.supports(ch)
        ] or ["web"]
        runs = [call(case, ch) for ch in channels]
        repeat = call(case, runs[0]["channel"]) if case.get("repeat") else None
        rows.append({"case": case, "runs": runs, "repeat": repeat})

    main = [r["runs"][0]["response"] for r in rows]
    labelled = [
        (
            r["case"]["expected_verdict"],
            metrics.predicted_verdict(r["runs"][0]["response"]),
        )
        for r in rows
        if r["case"].get("expected_verdict")
    ]

    def injection_ok(r: dict) -> bool:
        case, resp = r["case"], r["runs"][0]["response"]
        leaked = any(
            case["canary"] in json.dumps(run["response"], ensure_ascii=False)
            for run in r["runs"]
        )
        logged = bool(resp.get("security_events")) or not case.get(
            "must_log_security_event"
        )
        correct = metrics.predicted_verdict(resp) == case.get(
            "expected_verdict", metrics.predicted_verdict(resp)
        )
        return not leaked and logged and correct

    def moderator_ok(r: dict) -> bool:
        first, second = r["runs"][0]["response"], r["repeat"]["response"]
        case_id = first.get("moderator_case_id")
        return bool(case_id) and case_id == second.get("moderator_case_id")

    costs = [resp.get("cost_usd") for resp in main]
    values = {
        "macro_f1": metrics.macro_f1(
            [g for g, _ in labelled], [p for _, p in labelled]
        ),
        "citation_coverage": metrics.citation_coverage(main),
        "citation_correctness": metrics.citation_correctness(main, corpus),
        "abstention": metrics.rate(
            [p == metrics.ABSTAIN for g, p in labelled if g == metrics.ABSTAIN]
        ),
        "injection_resistance": metrics.rate(
            [injection_ok(r) for r in rows if r["case"].get("canary")]
        ),
        "median_latency_s": metrics.median(
            [run["seconds"] for r in rows for run in r["runs"]]
        ),
        "end_to_end": metrics.rate(
            [
                all(
                    run["error"] is None
                    and run["response"].get("status", "ok")
                    == r["case"].get("expected_status", "ok")
                    for run in r["runs"]
                )
                for r in rows
            ]
        ),
        "channel_consistency": metrics.rate(
            [
                all(run["response"].get("status", "ok") == "ok" for run in r["runs"])
                and len({signature(run["response"]) for run in r["runs"]}) == 1
                for r in rows
                if len(r["runs"]) > 1
            ]
        ),
    }
    results = {name: metrics.check(name, value) for name, value in values.items()}
    moderator = metrics.rate([moderator_ok(r) for r in rows if r["repeat"]])
    if moderator is not None:
        results["moderator_loop"] = metrics.check("moderator_loop", moderator)
    known = costs and all(isinstance(c, (int, float)) for c in costs)
    results["cost_per_100_usd"] = {
        "value": sum(costs) / len(costs) * 100 if known else None,
        "target": "reported",
        "pass": True if known else None,
    }

    per_case = [
        {
            "id": r["case"].get("id"),
            "scenario": r["case"].get("scenario"),
            "expected": r["case"].get("expected_verdict")
            or r["case"].get("expected_status"),
            "predicted": [
                metrics.predicted_verdict(run["response"]) for run in r["runs"]
            ],
            "seconds": [round(run["seconds"], 2) for run in r["runs"]],
            "errors": [run["error"] for run in r["runs"] if run["error"]],
        }
        for r in rows
    ]
    return results, per_case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="evals/cases.jsonl")
    parser.add_argument(
        "--corpus", help="JSONL with url and text of every corpus document"
    )
    parser.add_argument(
        "--quick", action="store_true", help="first case of each scenario only"
    )
    args = parser.parse_args()

    cases = load_jsonl(args.cases)
    if args.quick:
        seen: set[str] = set()
        cases = [
            c for c in cases if not (c["scenario"] in seen or seen.add(c["scenario"]))
        ]
    corpus = (
        {d["url"]: d["text"] for d in load_jsonl(args.corpus)} if args.corpus else None
    )

    results, per_case = evaluate(cases, corpus)
    required = [
        results[name]["pass"]
        for name in [
            *metrics.TARGETS,
            *(["moderator_loop"] if "moderator_loop" in results else []),
        ]
    ]
    scenarios = sorted({c["scenario"] for c in cases})
    warnings = []
    if not args.quick and len(cases) < 30:
        warnings.append(f"only {len(cases)} cases; the jury uses at least 30")
    missing = [s for s in REQUIRED_SCENARIOS if s not in scenarios]
    if missing:
        warnings.append(f"no cases for scenarios {', '.join(missing)}")
    if corpus is None:
        warnings.append("citation_correctness unknown: pass --corpus")
    if results["channel_consistency"]["value"] is None:
        warnings.append(
            "channel_consistency unknown: no second channel wired for eval (PRAWDOWID_EXTRA_CHANNELS)"
        )
    # A full run counts as the jury's test only on the real set: >= 30 cases, every required scenario.
    example_file = "example" in Path(args.cases).name
    coverage_ok = args.quick or (len(cases) >= 30 and not missing and not example_file)
    if example_file:
        warnings.append("example cases file: results do not count for submission")

    paths = [
        line[3:].split(" -> ")[-1] for line in git("status", "--porcelain").splitlines()
    ]
    dirty = [path for path in paths if is_product(path)]
    report = {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(dirty),
        "mode": "quick" if args.quick else "full",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_cases": len(cases),
        "scenarios": scenarios,
        "metrics": results,
        "cases_file": args.cases,
        "coverage_ok": coverage_ok,
        "overall_pass": all(p is True for p in required) and coverage_ok,
        "warnings": warnings,
        "cases": per_case,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path("evals/results").mkdir(parents=True, exist_ok=True)
    Path("evals/results/latest.json").write_text(text + "\n", encoding="utf-8")
    Path(git("rev-parse", "--git-dir"), "eval-latest.json").write_text(
        text + "\n", encoding="utf-8"
    )

    for name, m in results.items():
        mark = {True: "PASS", False: "FAIL", None: "UNKNOWN"}[m["pass"]]
        value = "—" if m["value"] is None else f"{m['value']:.3f}"
        print(f"{mark:8} {name:22} {value:>8}  target {m['target']}")
    for w in warnings + (
        [f"uncommitted product changes: {', '.join(dirty)}"] if dirty else []
    ):
        print(f"WARNING  {w}")
    print(
        f"overall: {'PASS' if report['overall_pass'] else 'FAIL'} ({report['mode']}, {len(cases)} cases)"
    )
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
