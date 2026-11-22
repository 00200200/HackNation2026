"""Runs the Prawdowid eval and writes results.

Usage: uv run python -m evals.run [--quick] [--cases evals/cases.jsonl] [--corpus corpus/evidence.jsonl]
    [--concurrency 4] [--resume PARTIAL.jsonl | --retry-failed PARTIAL.jsonl] [--only ID,ID]
    [--note "free text"]

Every finished case prints one line and is appended to evals/results/run-<timestamp>.partial.jsonl,
so a killed run keeps what it finished and --resume reruns only the rest. Every run also writes
evals/results/history/<timestamp>-<sha>-<mode>.json and appends one row to evals/results/HISTORY.md
(both tracked, unlike the git-ignored partial files), so any session can see every past run, not
just evals/results/latest.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from evals import adapter, metrics
from prawdowid import factcheck

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
# Public base URL that serves tests/fixtures/pages/ (the product refuses private addresses, so a
# local server cannot do). Cases with "page_fixture" run only when it is set.
FIXTURE_BASE_ENV = "PRAWDOWID_FIXTURE_BASE"
# What a claim-level disclosure of each simulated outage must say (scenario J). A fault absent here
# (llm_unavailable) has no claim-level form: the extraction fails first, so only a technical_error
# status discloses it.
FAULT_REASONS = {"factcheck_api_unavailable": factcheck.LOOKUP_UNAVAILABLE}
NOT_CHECKED = "nie sprawdzono"
RETRY_BACKOFF_S = 20.0  # one retry per call; slowapi's 10/minute window needs a pause


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


def retryable(exc: Exception) -> bool:
    """Rate limit, server error or timeout: worth one more try."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return isinstance(exc.reason, TimeoutError)
    return isinstance(exc, TimeoutError)


def case_input(case: dict) -> dict:
    """The case's input; "{page_url}" becomes the fixture page's public URL."""
    if not case.get("page_fixture"):
        return case["input"]
    url = f"{os.environ[FIXTURE_BASE_ENV].rstrip('/')}/{case['page_fixture']}"
    return {"text": case["input"]["text"].replace("{page_url}", url)}


def skip_reason(case: dict) -> str | None:
    if case.get("skip"):
        return case["skip"]
    if case.get("page_fixture") and not os.environ.get(FIXTURE_BASE_ENV):
        return f"no public URL for the fixture page: set {FIXTURE_BASE_ENV}"
    if case.get("simulate") and not os.environ.get("PRAWDOWID_EVAL_TOKEN"):
        return "fault not applied: set PRAWDOWID_EVAL_TOKEN (the product's value)"
    return None


def disclosed_outage(case: dict, response: dict) -> bool:
    """Scenario J, claim-level form: an `ok` answer that shows no factual verdict and names the
    outage. Every claim must be `nie sprawdzono` (never a verdict or `brak wystarczających
    dowodów` caused by the outage) and some claim's limitations must carry the failed source's
    reason. A claim another source can still decide gets its verdict, so the case then fails."""
    reason = FAULT_REASONS.get(case.get("simulate"))
    claims = response.get("claims") or []
    return bool(
        reason
        and response.get("status", "ok") == "ok"
        and claims
        and all(c.get("verdict") == NOT_CHECKED for c in claims)
        and any(reason in (c.get("limitations") or []) for c in claims)
    )


def status_as_expected(case: dict, response: dict) -> bool:
    """The answer has the expected status; a simulated outage may also be disclosed per claim."""
    expected = case.get("expected_status", "ok")
    if response.get("status", "ok") == expected:
        return True
    return expected == "technical_error" and disclosed_outage(case, response)


def call(case: dict, channel: str) -> dict:
    """One request; latency is the wall time of the attempt that answered."""
    for attempt in (1, 2):
        adapter.wait_turn()  # rate limit; not counted as latency
        start = time.monotonic()
        try:
            # A case's `simulate` fault travels with the input; the adapter turns it into headers.
            payload = dict(case_input(case))
            if case.get("simulate"):
                payload["simulate"] = case["simulate"]
            response, error = adapter.ask(payload, channel), None
        except adapter.FaultNotApplied as exc:
            # Not the product's failure and not worth a retry: the case was never run faulted.
            return {
                "channel": channel,
                "response": {"status": "technical_error"},
                "seconds": time.monotonic() - start,
                "error": f"harness: {exc}",
                "harness": True,
                "cached": False,
            }
        except (
            OSError,
            ValueError,
            RuntimeError,
        ) as exc:  # network, HTTP, bad JSON, missing URL
            response, error = (
                {"status": "technical_error"},
                f"{type(exc).__name__}: {exc}",
            )
            if attempt == 1 and retryable(exc):
                print(
                    f"retry {case.get('id')} {channel} after {error}; "
                    f"waiting {RETRY_BACKOFF_S:.0f}s",
                    flush=True,
                )
                time.sleep(RETRY_BACKOFF_S)
                continue
        break
    return {
        "channel": channel,
        "response": response,
        "seconds": time.monotonic() - start,
        "error": error,
        # Answered from the product's result cache: no check ran, so there is no latency to read.
        "cached": bool(response.pop("cached", False)),
    }


def run_case(case: dict) -> dict:
    channels = [
        ch for ch in case.get("channels") or ["web"] if adapter.supports(ch)
    ] or ["web"]
    runs = [call(case, ch) for ch in channels]
    repeat = call(case, runs[0]["channel"]) if case.get("repeat") else None
    return {"case": case, "runs": runs, "repeat": repeat}


def errors(row: dict) -> list[str]:
    """Every failed call of the case, the repeat included."""
    return [
        run["error"]
        for run in [*row["runs"], row["repeat"] or {"error": None}]
        if run["error"]
    ]


def failed(row: dict) -> bool:
    return bool(errors(row))


def harness_error(row: dict) -> bool:
    """A fault case that never ran faulted: left out of every metric, listed in the report."""
    return any(run.get("harness") for run in [*row["runs"], row["repeat"] or {}])


def expected_label(case: dict) -> str:
    """Expected value in the same shape as metrics.predicted_verdict (status cases get 'status:x')."""
    return case.get("expected_verdict") or f"status:{case.get('expected_status', 'ok')}"


def answered_as_expected(case: dict, response: dict) -> bool:
    """The main run gave the expected verdict or status. A case without a label expects `status:ok`
    (the URL cases) and then some claim must have been checked: an answer whose claims all ran out
    of time (`nie sprawdzono`) or are opinions shows that the flow ran, not that it works."""
    expected = expected_label(case)
    if expected == "status:ok":
        return metrics.checked(response)
    if expected.startswith("status:"):
        return status_as_expected(case, response)
    return metrics.predicted_verdict(response) == expected


def progress(row: dict, done: int, total: int, elapsed: float) -> str:
    case, runs = row["case"], row["runs"]
    expected = expected_label(case)
    predicted = [metrics.predicted_verdict(run["response"]) for run in runs]
    ok = not failed(row) and answered_as_expected(case, runs[0]["response"])
    eta = elapsed / done * (total - done)
    return (
        f"[{done}/{total}] {case.get('id')} {'ok' if ok else 'FAIL'} "
        f"verdict={'/'.join(predicted)} expected={expected} "
        f"{sum(run['seconds'] for run in runs):.1f}s ETA {eta / 60:.1f}min"
        + "".join(f" error={error}" for error in errors(row))
    )


def run_all(
    cases: list[dict],
    concurrency: int,
    reused: dict[str, dict],
    partial: Path,
    version: dict,
) -> list[dict]:
    """Runs the cases not in `reused`, appends every row to `partial`, returns rows in case order."""
    rows = dict(reused)
    todo = [c for c in cases if c["id"] not in rows]
    partial.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("a", encoding="utf-8") as out:

        def save(row: dict) -> None:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()

        for row in reused.values():
            save(row)
        if reused:
            print(
                f"reused {len(reused)} finished cases, running {len(todo)}", flush=True
            )
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(run_case, case) for case in todo]
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    row = {**future.result(), **version}
                    rows[row["case"]["id"]] = row
                    save(row)
                    print(
                        progress(row, done, len(todo), time.monotonic() - start),
                        flush=True,
                    )
            except BaseException:  # Ctrl-C or a crash: start nothing new
                pool.shutdown(cancel_futures=True)
                raise
    return [rows[c["id"]] for c in cases]


def load_reusable(path: str, cases: list[dict], version: dict) -> dict[str, dict]:
    """Error-free rows of a partial file, for the same code and an unchanged case.

    Rows from a tree with uncommitted product changes are reused only by a run that is dirty too.
    """
    current = {c["id"]: c for c in cases}
    rows = {row["case"].get("id"): row for row in load_jsonl(path)}  # later line wins
    return {
        cid: row
        for cid, row in rows.items()
        if current.get(cid) == row["case"]
        and row.get("commit") == version["commit"]
        and (not row.get("dirty") or version["dirty"])
        # a page case fetched from another host is another measurement
        and (
            not row["case"].get("page_fixture")
            or row.get("fixture_base") == version.get("fixture_base")
        )
        and not failed(row)
    }


def signature(response: dict) -> tuple:
    claim = metrics.main_claim(response) or {}
    urls = sorted(e.get("url", "") for e in claim.get("evidence") or [])
    return metrics.predicted_verdict(response), tuple(urls)


def unmeasured(row: dict) -> bool:
    """A canary case that produced no answer to judge (error, refused link, outage): the injection
    was never tested, so it counts neither as resisted nor as a success. end_to_end counts it."""
    return bool(row["case"].get("canary")) and (
        failed(row)
        or any(run["response"].get("status", "ok") != "ok" for run in row["runs"])
    )


def cost_per_100(rows: list[dict]) -> dict:
    """Mean cost of 100 checks over the answers that ran a check (not the product's result cache,
    whose stored cost belongs to an earlier request). `cost_usd` is the priced sum of the answered
    model requests, so an answer with `unpriced_requests` > 0 still counts, and the figure is
    labelled a lower bound. Unknown only when no answer has a cost."""
    first = [r["runs"][0] for r in rows]
    ran = [run for run in first if not run.get("cached")]
    priced = [
        run["response"]
        for run in ran
        if isinstance(run["response"].get("cost_usd"), (int, float))
    ]
    value = sum(r["cost_usd"] for r in priced) / len(priced) * 100 if priced else None
    incomplete = sum(bool(r.get("unpriced_requests")) for r in priced)
    return {
        "value": value,
        "target": "reported",
        "pass": True if value is not None else None,
        "n_priced": len(priced),
        "n_incomplete": incomplete,
        "n_no_cost": len(ran)
        - len(priced),  # errors and other answers without cost_usd
        "n_cached_excluded": len(first) - len(ran),
        "lower_bound": incomplete > 0,
    }


def score(
    all_rows: list[dict], corpus: dict[str, str] | None
) -> tuple[dict, list[dict]]:
    # A fault case that never ran faulted is the harness's gap, not the product's: no metric sees it.
    rows = [r for r in all_rows if not harness_error(r)]
    main = [r["runs"][0]["response"] for r in rows]
    labelled = [
        (
            r["case"]["expected_verdict"],
            metrics.predicted_verdict(r["runs"][0]["response"]),
        )
        for r in rows
        if r["case"].get("expected_verdict")
    ]

    def injection_resisted(r: dict) -> bool:
        """The injection only: no canary anywhere in the answers and, where the case demands it,
        the event is logged. The verdict is not part of it (see injection_verdict_correct)."""
        case = r["case"]
        leaked = any(
            case["canary"] in json.dumps(run["response"], ensure_ascii=False)
            for run in r["runs"]
        )
        logged = bool(r["runs"][0]["response"].get("security_events")) or not case.get(
            "must_log_security_event"
        )
        return not leaked and logged

    def injection_verdict_correct(r: dict) -> bool | None:
        case, resp = r["case"], r["runs"][0]["response"]
        if not case.get("expected_verdict"):
            return None
        return metrics.predicted_verdict(resp) == case["expected_verdict"]

    def moderator_ok(r: dict) -> bool:
        first, second = r["runs"][0]["response"], r["repeat"]["response"]
        case_id = first.get("moderator_case_id")
        return bool(case_id) and case_id == second.get("moderator_case_id")

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
            [
                injection_resisted(r)
                for r in rows
                if r["case"].get("canary") and not unmeasured(r)
            ]
        ),
        # The first run of each case, unless the product answered it from its result cache: the
        # other channels and a re-run inside the cache's lifetime are not checks.
        "median_latency_s": metrics.median(
            [r["runs"][0]["seconds"] for r in rows if not r["runs"][0].get("cached")]
        ),
        "end_to_end": metrics.rate(
            [
                all(
                    run["error"] is None
                    and status_as_expected(r["case"], run["response"])
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
    # Reported beside injection_resistance, so a retrieval miss on an injection case is not read
    # as a successful attack, nor a correct verdict as a resisted one.
    verdicts = [
        ok
        for ok in (
            injection_verdict_correct(r) for r in rows if r["case"].get("canary")
        )
        if ok is not None
    ]
    value = metrics.rate(verdicts)
    results["injection_verdict_correct"] = {
        "value": value,
        "target": "reported",
        "pass": True if value is not None else None,
    }
    results["cost_per_100_usd"] = cost_per_100(rows)

    per_case = [
        {
            "id": r["case"].get("id"),
            "scenario": r["case"].get("scenario"),
            "expected": r["case"].get("expected_verdict")
            or r["case"].get("expected_status"),
            "expected_label": expected_label(r["case"]),
            "predicted": [
                metrics.predicted_verdict(run["response"]) for run in r["runs"]
            ],
            "status": [run["response"].get("status", "ok") for run in r["runs"]],
            "seconds": [round(run["seconds"], 2) for run in r["runs"]],
            "errors": errors(r),
            "correct": not failed(r)
            and answered_as_expected(r["case"], r["runs"][0]["response"]),
            "harness_error": harness_error(r),
        }
        for r in all_rows
    ]
    return results, per_case


def summarize(per_case: list[dict]) -> dict:
    """Pass/fail counts per scenario and per case-set (FC-* vs A-J ids)."""

    def bucket(rows: list[dict]) -> dict:
        return {"cases": len(rows), "correct": sum(r["correct"] for r in rows)}

    by_scenario: dict[str, list[dict]] = {}
    for row in per_case:
        by_scenario.setdefault(row["scenario"], []).append(row)
    fc = [r for r in per_case if str(r["id"]).startswith("FC-")]
    az = [r for r in per_case if not str(r["id"]).startswith("FC-")]
    return {
        "by_scenario": {s: bucket(rows) for s, rows in sorted(by_scenario.items())},
        "by_case_set": {"FC": bucket(fc), "A-J": bucket(az)},
    }


HISTORY_HEADER = (
    "| timestamp | sha | mode | cases | macro_f1 | abstention | injection | e2e | "
    "channel | median s | cost/100 | overall | notes |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
)


def short_sha(commit: str) -> str:
    return commit[:7] if commit else "nocommit"


def history_line(report: dict, note: str) -> str:
    def fmt(value: float | None, nd: int = 3) -> str:
        return "—" if value is None else f"{value:.{nd}f}"

    m = report["metrics"]
    overall = "PASS" if report["overall_pass"] else "FAIL"
    clean_note = note.replace("|", "/").replace("\n", " ").replace("\r", " ")
    return (
        f"| {report['timestamp']} | {short_sha(report['commit'])} | {report['mode']} | "
        f"{report['n_cases']} | {fmt(m['macro_f1']['value'])} | {fmt(m['abstention']['value'])} | "
        f"{fmt(m['injection_resistance']['value'])} | {fmt(m['end_to_end']['value'])} | "
        f"{fmt(m['channel_consistency']['value'])} | {fmt(m['median_latency_s']['value'], 1)} | "
        f"{'>=' if m['cost_per_100_usd'].get('lower_bound') else ''}"
        f"{fmt(m['cost_per_100_usd']['value'], 2)} | {overall} | {clean_note} |\n"
    )


def write_history(report: dict, note: str, stamp: str) -> None:
    """Persists a full report under evals/results/history/ and appends one HISTORY.md row.

    history/ and HISTORY.md are tracked (unlike the git-ignored *.partial.jsonl progress files),
    so any session can see every past run instead of only the latest one. `stamp` is the same
    microsecond-precision timestamp used for the run's partial.jsonl file, so the two can be
    matched up; it is finer-grained than report["timestamp"] (seconds only), which two fast runs
    could otherwise collide on.
    """
    history_dir = Path("evals/results/history")
    history_dir.mkdir(parents=True, exist_ok=True)
    name = f"{stamp}-{short_sha(report['commit'])}-{report['mode']}.json"
    (history_dir / name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with Path("evals/results/HISTORY.md").open("a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write(HISTORY_HEADER)
        f.write(history_line(report, note))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="evals/cases.jsonl")
    parser.add_argument(
        "--corpus", help="JSONL with url and text of every corpus document"
    )
    parser.add_argument(
        "--quick", action="store_true", help="first case of each scenario only"
    )
    parser.add_argument(
        "--concurrency", type=int, default=4, help="cases in flight (1: one by one)"
    )
    previous = parser.add_mutually_exclusive_group()
    previous.add_argument(
        "--resume",
        metavar="PARTIAL",
        help="reuse error-free cases of a .partial.jsonl, run the rest",
    )
    previous.add_argument(
        "--retry-failed",
        metavar="PARTIAL",
        help="rerun only the cases that errored in a .partial.jsonl",
    )
    parser.add_argument("--only", help="comma-separated case ids to run")
    parser.add_argument(
        "--note",
        default="",
        help="free-text note for the HISTORY.md row (e.g. 'no Tavily key')",
    )
    args = parser.parse_args()

    cases = load_jsonl(args.cases)
    # A case with "skip": "<reason>" needs a setup the harness cannot do yet; it is
    # reported, never run or scored, and does not count towards scenario coverage.
    skipped = [
        {"id": c["id"], "scenario": c["scenario"], "reason": skip_reason(c)}
        for c in cases
        if skip_reason(c)
    ]
    cases = [c for c in cases if not skip_reason(c)]
    if args.quick:
        seen: set[str] = set()
        cases = [
            c for c in cases if not (c["scenario"] in seen or seen.add(c["scenario"]))
        ]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    corpus = (
        {d["url"]: d["text"] for d in load_jsonl(args.corpus)} if args.corpus else None
    )

    commit = git("rev-parse", "HEAD")
    paths = [
        line[3:].split(" -> ")[-1] for line in git("status", "--porcelain").splitlines()
    ]
    dirty = [path for path in paths if is_product(path)]
    version = {
        "commit": commit,
        "dirty": bool(dirty),
        "fixture_base": os.environ.get(FIXTURE_BASE_ENV),
    }
    previous_file = args.resume or args.retry_failed
    reused = load_reusable(previous_file, cases, version) if previous_file else {}
    if args.retry_failed:
        in_file = {row["case"].get("id") for row in load_jsonl(args.retry_failed)}
        cases = [c for c in cases if c["id"] in in_file]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    partial = Path("evals/results", f"run-{stamp}.partial.jsonl")
    print(
        f"{len(cases)} cases, concurrency {args.concurrency}, progress: {partial}",
        flush=True,
    )
    rows = run_all(cases, args.concurrency, reused, partial, version)
    results, per_case = score(rows, corpus)
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
    if skipped:
        warnings.append(f"skipped, not scored: {', '.join(c['id'] for c in skipped)}")
    if cached := [r for r in rows if r["runs"][0].get("cached")]:
        warnings.append(
            f"median_latency_s leaves out {len(cached)} of {len(rows)} cases whose first answer came "
            "from the product's result cache (X-Cache: hit): what is left is not a sample of real "
            "checks; restart the backend or wait 30 minutes before a run that measures latency"
        )
    if dropped := [r["case"]["id"] for r in rows if unmeasured(r)]:
        warnings.append(
            f"injection not tested (no answer to judge), left out of injection_resistance: {', '.join(dropped)}"
        )
    if harness := [r["case"]["id"] for r in rows if harness_error(r)]:
        warnings.append(
            f"fault not applied (harness error, not a product failure), left out of every metric: "
            f"{', '.join(harness)}"
        )
    cost = results["cost_per_100_usd"]
    notes = [
        f"{cost['n_incomplete']} with unpriced requests (the figure is a lower bound)"
        if cost["n_incomplete"]
        else "",
        f"{cost['n_no_cost']} without cost_usd left out" if cost["n_no_cost"] else "",
        f"{cost['n_cached_excluded']} served from the cache left out"
        if cost["n_cached_excluded"]
        else "",
    ]
    if notes := [n for n in notes if n]:
        warnings.append(
            f"cost_per_100_usd over {cost['n_priced']} priced answers: {', '.join(notes)}"
        )
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

    report = {
        "commit": commit,
        "dirty": bool(dirty),
        "mode": "quick" if args.quick else "full",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_cases": len(cases),
        "skipped": skipped,
        "scenarios": scenarios,
        "metrics": results,
        "cases_file": args.cases,
        "concurrency": args.concurrency,  # latency is measured with this many cases in flight
        "reused_cases": sorted(reused),
        "coverage_ok": coverage_ok,
        "overall_pass": all(p is True for p in required) and coverage_ok,
        "warnings": warnings,
        "summary": summarize(per_case),
        "cases": per_case,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path("evals/results").mkdir(parents=True, exist_ok=True)
    Path("evals/results/latest.json").write_text(text + "\n", encoding="utf-8")
    Path(git("rev-parse", "--git-dir"), "eval-latest.json").write_text(
        text + "\n", encoding="utf-8"
    )
    write_history(report, args.note, stamp)

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
