"""Print the same metrics for the held-out FC-* cases and for the rest of the set.

FC-* cases were written by a different person and never used while tuning, so they are the closer
estimate of the jury's hidden comparison set. Reads a results JSON (default
evals/results/latest.json); does not run anything.

    uv run python -m evals.split_report [path/to/results.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals import metrics

DEFAULT = Path(__file__).parent / "results" / "latest.json"


def split(rows: list[dict]) -> dict[str, list[dict]]:
    held_out = [r for r in rows if str(r["id"]).startswith("FC-")]
    rest = [r for r in rows if not str(r["id"]).startswith("FC-")]
    return {"FC-* (held out)": held_out, "rest": rest}


def group_metrics(rows: list[dict]) -> dict:
    """Metrics from per-case rows; `predicted` and `seconds` hold one entry per channel run."""
    scored = [r for r in rows if not r.get("errors") and r.get("predicted")]
    labelled = [
        (r["expected"], r["predicted"][0])
        for r in scored
        if r["expected"] in metrics.VERDICTS
    ]
    return {
        "cases": len(rows),
        "errored": len(rows) - len(scored),
        "accuracy": metrics.rate(
            [
                r["predicted"][0] == r.get("expected_label", r["expected"])
                for r in scored
            ]
        ),
        "macro_f1": metrics.macro_f1(
            [g for g, _ in labelled], [p for _, p in labelled]
        ),
        "abstention": metrics.rate(
            [p == metrics.ABSTAIN for g, p in labelled if g == metrics.ABSTAIN]
        ),
        "median_latency_s": metrics.median(
            [s for r in scored for s in r.get("seconds", [])]
        ),
    }


def format_report(report: dict) -> str:
    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    head = f"commit {str(report.get('commit', ''))[:7]}, mode {report.get('mode')}"
    lines = [
        head,
        f"{'group':<16}{'cases':>6}{'errored':>9}{'accuracy':>10}{'macro_f1':>10}{'abstention':>12}{'median_s':>10}",
    ]
    for name, rows in split(report["cases"]).items():
        m = group_metrics(rows)
        lines.append(
            f"{name:<16}{m['cases']:>6}{m['errored']:>9}{fmt(m['accuracy']):>10}"
            f"{fmt(m['macro_f1']):>10}{fmt(m['abstention']):>12}{fmt(m['median_latency_s']):>10}"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT
    print(format_report(json.loads(path.read_text("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
