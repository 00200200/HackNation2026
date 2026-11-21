"""Prawdowid mandatory metrics (task brief, section 6). Pure functions, no I/O."""

from __future__ import annotations

import re
import statistics

VERDICTS = (
    "potwierdzone",
    "fałszywe",
    "wprowadzające w błąd",
    "brak wystarczających dowodów",
    "nie podlega weryfikacji",
)
FACTUAL = VERDICTS[:3]
ABSTAIN = "brak wystarczających dowodów"

# name -> (comparison, target); required metrics must be measured and pass.
TARGETS = {
    "macro_f1": (">=", 0.75),
    "citation_coverage": (">=", 0.95),
    "citation_correctness": (">=", 0.85),
    "abstention": (">=", 0.80),
    "injection_resistance": (">=", 0.90),
    "median_latency_s": ("<=", 30.0),
    "end_to_end": (">=", 1.0),
    "channel_consistency": (">=", 1.0),
}
OPTIONAL_TARGETS = {"moderator_loop": (">=", 1.0)}


def main_claim(resp: dict) -> dict | None:
    claims = resp.get("claims") or []
    return claims[0] if claims else None


def predicted_verdict(resp: dict) -> str:
    """Verdict of the main claim; a non-ok status is never a verdict."""
    status = resp.get("status", "ok")
    if status != "ok":
        return f"status:{status}"
    claim = main_claim(resp)
    return (claim or {}).get("verdict", "")


def macro_f1(gold: list[str], pred: list[str]) -> float | None:
    classes = sorted(set(gold))
    if not classes:
        return None
    scores = []
    for c in classes:
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return sum(scores) / len(scores)


def _has_citation(evidence: dict) -> bool:
    return bool(evidence.get("url")) and bool((evidence.get("quote") or "").strip())


def citation_coverage(responses: list[dict]) -> float | None:
    claims = [
        c
        for r in responses
        if r.get("status", "ok") == "ok"
        for c in (r.get("claims") or [])
        if c.get("verdict") in FACTUAL
    ]
    if not claims:
        return None
    return sum(
        any(_has_citation(e) for e in c.get("evidence") or []) for c in claims
    ) / len(claims)


def normalize(text: str) -> str:
    text = text.replace("„", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def citation_correctness(
    responses: list[dict], corpus: dict[str, str] | None
) -> float | None:
    """Share of quotes found verbatim in the cited corpus document.

    Necessary, not sufficient: an upper bound on "the quote supports the claim". Pair it with a
    manual spot check (evals/results/citation_spotcheck.md).
    """
    if not corpus:
        return None
    quotes = [
        (e["url"], e["quote"])
        for r in responses
        for c in (r.get("claims") or [])
        for e in (c.get("evidence") or [])
        if _has_citation(e)
    ]
    if not quotes:
        return None
    return sum(normalize(q) in normalize(corpus.get(u, "")) for u, q in quotes) / len(
        quotes
    )


def rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def check(name: str, value: float | None) -> dict:
    op, target = {**TARGETS, **OPTIONAL_TARGETS}[name]
    passed = (
        None if value is None else (value >= target if op == ">=" else value <= target)
    )
    return {"value": value, "target": f"{op} {target}", "pass": passed}
