"""Print metrics for the FC-* cases and for the rest of the set, with the definitions of evals.run.

Errored calls count as wrong (`status:technical_error`) and their time counts toward latency, exactly
as in evals.run.score and evals.run.summarize. Provenance of the FC-* set is UNCONFIRMED, see
docs/eval-notes.md. Reads a results JSON (default evals/results/latest.json); runs nothing.

    uv run python -m evals.split_report [path/to/results.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals import metrics

DEFAULT = Path(__file__).parent / "results" / "latest.json"


ERRORED = "status:technical_error"


def split(rows: list[dict]) -> dict[str, list[dict]]:
    fc = [r for r in rows if str(r["id"]).startswith("FC-")]
    rest = [r for r in rows if not str(r["id"]).startswith("FC-")]
    return {"FC-*": fc, "rest": rest}


def label(row: dict) -> str:
    """Expected label; old result files lack `expected_label`, so mirror evals.run.expected_label."""
    if row.get("expected_label"):
        return row["expected_label"]
    expected = row.get("expected")
    return expected if expected in metrics.VERDICTS else f"status:{expected or 'ok'}"


def first_prediction(row: dict) -> str:
    return (row.get("predicted") or [ERRORED])[0]


def group_metrics(rows: list[dict]) -> dict:
    """Per-case rows to metrics; `predicted` and `seconds` hold one entry per channel run."""
    labelled = [
        (label(r), first_prediction(r)) for r in rows if label(r) in metrics.VERDICTS
    ]
    correct = [not r.get("errors") and first_prediction(r) == label(r) for r in rows]
    return {
        "cases": len(rows),
        "errored": sum(bool(r.get("errors")) for r in rows),
        "accuracy": metrics.rate(correct),
        "macro_f1": metrics.macro_f1(
            [g for g, _ in labelled], [p for _, p in labelled]
        ),
        "abstention": metrics.rate(
            [p == metrics.ABSTAIN for g, p in labelled if g == metrics.ABSTAIN]
        ),
        "median_latency_s": metrics.median(
            [s for r in rows for s in r.get("seconds", [])]
        ),
    }


def format_report(report: dict) -> str:
    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    head = f"commit {str(report.get('commit', ''))[:7]}, mode {report.get('mode')}"
    lines = [
        head,
        f"{'group':<8}{'cases':>6}{'errored':>9}{'accuracy':>10}{'macro_f1':>10}{'abstention':>12}{'median_s':>10}",
    ]
    for name, rows in split(report["cases"]).items():
        m = group_metrics(rows)
        lines.append(
            f"{name:<8}{m['cases']:>6}{m['errored']:>9}{fmt(m['accuracy']):>10}"
            f"{fmt(m['macro_f1']):>10}{fmt(m['abstention']):>12}{fmt(m['median_latency_s']):>10}"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT
    print(format_report(json.loads(path.read_text("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
