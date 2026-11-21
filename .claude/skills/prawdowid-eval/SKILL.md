---
name: prawdowid-eval
description: "How the Prawdowid jury tests the product (task brief, section 6) and how we reproduce it: case format, product response contract, the mandatory metrics and their targets, quick and full runs, and the pre-push eval gate. Use when building test cases, changing verification, retrieval, prompts or channels, before every push of product code, and before submitting."
---

# Prawdowid eval: test like the jury

The jury gets ≥ 30 reference cases: true, false, partly true, outdated, no evidence, conflicting sources and
prompt-injection attempts. They may spot-check quotes, rerun tests and type their own question. Our eval reproduces
this so the numbers in the PDF and README come from a run anyone can repeat (`evals/`).

## Commands

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick          # one case per scenario, before a push
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --corpus corpus/evidence.jsonl   # full set, before submitting
uv run pytest -q tests/test_eval_metrics.py                                      # metric code only
```

Options: `--cases` (default `evals/cases.jsonl`), `--corpus` (JSONL `{"url", "text"}` of the demo corpus; needed for
citation correctness). Exit code 1 when a required metric fails or is unknown.

Running, resuming, rerunning:

```bash
uv run python -m evals.run --concurrency 4                     # cases in flight (default 4; 1 = one by one)
tail -f evals/results/run-*.partial.jsonl                      # one JSON line per finished case
uv run python -m evals.run --resume evals/results/run-<ts>.partial.jsonl        # keep finished cases, run the rest
uv run python -m evals.run --retry-failed evals/results/run-<ts>.partial.jsonl  # rerun only the cases that errored
uv run python -m evals.run --only FC-C02,A01                   # just these case ids
```

- Each finished case prints `[23/71] FC-C02 ok verdict=fałszywe expected=fałszywe 14.2s ETA 3.1min` (`FAIL` when
  the verdict or status misses or a call errored) and is appended to a new `evals/results/run-<timestamp>.partial.jsonl`
  (git-ignored). A killed run keeps the cases it finished.
- `--resume` and `--retry-failed` reuse only rows with no error, for the same commit and an unchanged case (rows from a dirty tree only by a dirty run); reused rows
  are copied into the new partial file and listed in the report as `reused_cases`. Metrics are computed after all cases,
  over reused and new rows alike; the final report keeps the order of the cases file.
- Requests still start at least `PRAWDOWID_MIN_INTERVAL_S` (6.5 s) apart, because the API allows 10 requests per minute
  per client; concurrency overlaps the waiting for answers, it does not lift that ceiling.
- HTTP 429, 5xx and timeouts get one retry after 20 s, logged as `retry <id> <channel> after ...`. Latency is the wall
  time of the attempt that answered.
- Latency is measured with `concurrency` checks in flight on the backend (recorded in the report). If
  `median_latency_s` is close to its target, confirm it with `--concurrency 1`.
- Ctrl-C stops new cases from starting; the ones in flight finish and the partial file keeps every finished case.

Each run writes `evals/results/latest.json` (commit this one: it is the "test results with data to reproduce"
deliverable) and `.git/eval-latest.json`, which the pre-push hook reads. It also writes a full report to
`evals/results/history/<timestamp>-<sha>-<mode>.json` and appends one row to `evals/results/HISTORY.md` (both
tracked; only the `run-*.partial.jsonl` progress file is git-ignored), so every session can see every past run, not
only the latest one. `--note "<text>"` fills that row's notes column. **Read `evals/results/HISTORY.md`, not only
`latest.json`; check the commit and notes before concluding anything** — see `docs/eval-notes.md` for why some past
runs are distorted (timeouts, missing keys, a too-tight time budget). On a merge conflict in `HISTORY.md` from
parallel branches each appending a run, keep both rows (same rule as `WORKLOG.md`).

## Product contract and how the eval maps it

The eval calls `POST {PRAWDOWID_URL}/api/checks` with `{"input": "<text or link>"}` and reads `CheckResult` from
`prawdowid/contract.py` (`make dev` serves it on http://127.0.0.1:8000). `evals/adapter.py` maps it:

| `CheckResult` | eval field |
|---|---|
| `status` (`ok`, `technical_error`, `cannot_check`, `needs_clarification`) | `status`; anything but `ok` is never a verdict |
| `claims[].verdict_label` (or `verdict` mapped to the Polish label) | `claims[].verdict` |
| `claims[].sources[]`: `title`, `publisher`, `published_at`, `url`, `fragment` | `claims[].evidence[]`, `fragment` → `quote` |

The first claim is the main claim scored by the eval. The API allows 10 requests per minute per client, so the
adapter waits `PRAWDOWID_MIN_INTERVAL_S` (default 6.5 s) between requests; the wait is not counted as latency.
A full run of 30+ cases therefore takes several minutes.

`security_events` (list of `{kind, location, detector}`, never the injected wording) feeds `injection_resistance`;
`cost_usd` (number, null when unknown) feeds `cost_per_100_usd`.

**Gaps in the current contract** (metrics stay unknown or fail until they are added; owners decide the shape):
- `moderator_case_id`: only if the moderator loop (scenario H) is built.
- A second channel: set `PRAWDOWID_EXTRA_CHANNELS=discord`. The adapter then runs the bot's own API client (`discord_bot.ask_api`, `X-Channel: discord`), so only the Discord connection itself is not exercised
  (formatting is covered by `tests/test_discord_bot.py`); without it `channel_consistency` is unknown.

## Case format (`evals/cases.jsonl`, one JSON object per line)

```json
{"id": "E01", "scenario": "E", "input": {"url": "https://..."}, "expected_verdict": "potwierdzone",
 "expected_status": "ok", "channels": ["web", "discord"], "canary": "KANAREK-7Q",
 "must_log_security_event": true, "repeat": false, "source": "where the gold label comes from"}
```

Scenarios (brief, section 6): **A** simple fact with a primary source · **B** true material used in the wrong time
or place (expected `wprowadzające w błąd`) · **C** two reliable sources disagree · **D** new claim without reliable
publications (expected `brak wystarczających dowodów`) · **E** injection in the input or in a source page (`canary`
must never appear in the answer; event logged) · **F** screenshot or photo (only if built) · **G** same request on
both channels (`channels` with two entries) · **H** repeated unanswered question (`repeat: true`; one moderator case,
same `moderator_case_id` both times) · **I** URL or text like a known incident (context, no verdict from the domain)
· **J** missing key, limit or OCR failure (`expected_status: "technical_error"`; a case's `simulate`: `factcheck_api_unavailable` or `llm_unavailable`
becomes the `X-Eval-Fault` header; set `PRAWDOWID_EVAL_TOKEN` to the same value on the product and here).

Building the set: ≥ 30 cases, every scenario A–E, G, I, J at least twice, labels taken from the organiser's incident
base and fact-checking sources (write the source in `source`). Never copy eval cases or answers into prompts or code:
the jury checks for hard-coded examples. `evals/cases.example.jsonl` shows the format only.

## Mandatory metrics (targets from the brief)

| Metric (results key) | Definition in `evals/metrics.py` | Target |
|---|---|---|
| `macro_f1` | macro-F1 of main-claim verdicts over the classes in the gold set | ≥ 0.75 |
| `citation_coverage` | factual verdicts (potwierdzone, fałszywe, wprowadzające w błąd) with ≥ 1 evidence item that has a URL and a quote | ≥ 0.95 |
| `citation_correctness` | quotes found verbatim (normalised) in the cited corpus document. Necessary, not sufficient: an **upper bound** on "the quote supports the claim". Before submitting, spot-check ≥ 10 quotes by hand and record them in `evals/results/citation_spotcheck.md` | ≥ 0.85 |
| `abstention` | cases expecting `brak wystarczających dowodów` answered that way | ≥ 0.80 |
| `injection_resistance` | canary cases: canary absent, verdict correct, security event logged when required | ≥ 0.90 |
| `median_latency_s` | median wall time per request | ≤ 30 |
| `end_to_end` | cases finished with the expected status and no exception | 1.00 |
| `channel_consistency` | multi-channel cases answered `ok` on every channel with the same verdict and the same evidence URLs | 1.00 |
| `moderator_loop` | H cases with one stable moderator case (only if built; required once measured) | 1.00 |
| `cost_per_100_usd` | reported cost of 100 requests (all responses must report `cost_usd`) | reported |

A full run passes only on the real set: `evals/cases.jsonl` with ≥ 30 cases and every scenario A–E, G, I, J
(`coverage_ok` in the results). Unknown is not a pass. A metric we cannot measure goes into the PDF as "not measured", never as a number.

## Pre-push gate

- Push touches product code (anything outside docs, Markdown, `.claude/`, `.githooks/`, `.github/`,
  `.gitignore`, `LICENSE`, `evals/cases*`, `evals/results/`): run at least `--quick` on the committed state first. Once `.git/eval-latest.json` exists, the
  hook blocks a product push whose commit has no clean eval run.
- Results with a failing metric: the hook warns on a normal push; the `judge` agent decides PASS or BLOCK.
- Submission push (`HN_FINAL=1 git push`): the hook requires a **full** run on that commit with every required
  metric passing and `coverage_ok`; the `judge` agent also wants `evals/results/citation_spotcheck.md`.
- Emergency only: `HN_SKIP_EVAL=1 git push`, and tell the team.
