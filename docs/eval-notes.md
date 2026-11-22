# Eval notes

Read this together with [`evals/results/HISTORY.md`](../evals/results/HISTORY.md), not only
`evals/results/latest.json`: the latest file is one snapshot, and a session that only looks at it
draws wrong conclusions about product quality. **Rule: check the commit and the notes column
before concluding anything from a number.**

The three oldest rows in HISTORY.md are reconstructed from memory of runs made before this
history mechanism existed: there is no JSON for them (no `evals/results/history/*.json` file), the
numbers come from whoever ran them, and nothing beyond what is written below is confirmed.

## Run 2 (2026-11-21 ~20:44 UTC, commit `8c6f396`, full, 71 cases) — the one most likely to be misread

Config: web + discord channels, no corpus (`citation_correctness` not measured), Tavily +
EUvsDisinfo + Google Fact Check keys set.

Results: macro_f1 0.498, citation_coverage 1.000, citation_correctness not measured, abstention
0.583, injection_resistance 0.571, median latency 18.2 s, end_to_end 0.704, channel_consistency
0.000, moderator_loop 0.000, cost not measured. Skipped: FC-J01, FC-J02.

**Why the FC-* numbers are not a quality signal:**

- Anthropic timeouts from case FC-A02 onward turned roughly 20 cases into `technical_error`.
- The 25 s `PRAWDOWID_CHECK_BUDGET_S` was too tight for this run's retrieval fan-out, so many
  claims came back `nie sprawdzono` (not checked) rather than a real verdict.
- J01/J02's `simulate` fault was not applied by the harness (no product eval switch existed yet),
  so those two cases were scored normally and came back wrong (`J 0/2` below) instead of hitting
  the fault they were meant to test. It is FC-J01/FC-J02 (not J01/J02) that were skipped outright.

Per case-set:

- **A–J** (41 cases): 21 correct. By scenario: A 8/15, B 0/4, C 1/4, D 4/4, E 4/4, G 0/2, H 2/2,
  I 2/4, J 0/2.
- **FC-*** (30 cases scored): 1 correct (19 `technical_error`, 7 `nie sprawdzono`) — this set is
  the one distorted by the timeouts and the budget above; its low score is an infrastructure
  artifact of that run, not evidence the product can't verify FC-* claims.

What was in the pipeline for this run: claim extraction, Google Fact Check, EUvsDisinfo (context
only, never a verdict), Tavily web search, rerank, judge, `decide()`, per-claim fan-out, incident
matcher (empty base — no incidents loaded).

What was **not** in it: the evidence corpus from #49 (not wired into `verify()` yet), gov.pl
search, the CodeRabbit fixes from #51, the runner improvements from #52 (concurrency, resume,
retry), or this history mechanism (`evals/results/HISTORY.md`, added after this run).

## Run 1 (same commit `8c6f396`, invalid)

Only `GOOGLE_FACTCHECK_API_KEY` was set — no `TAVILY_API_KEY` or `EUVSDISINFO_API_KEY`, so only
Fact Check was searched. macro_f1 0.353, abstention 1.00, injection_resistance 0.571, median
latency 5.8 s, end_to_end 0.972, channel_consistency 1.00. Mode and case count were not recorded
anywhere retrievable, so they are marked UNCONFIRMED in HISTORY.md rather than guessed.

## Earlier quick runs (before Tavily was integrated)

8 cases, one per scenario: macro_f1 0.25, end_to_end 0.875, abstention 1.00,
injection_resistance 1.00, median latency ~15 s, cost $1.65 per 100 checks. A separate Tavily
smoke test on the same 8 quick cases got at least one allowlisted source for 7/8 of them; the same
smoke test against plain DuckDuckGo got 0/8.

## Levers for the next run (not yet done)

- Raise `PRAWDOWID_CHECK_BUDGET_S` (currently 25 s; try ~45 s) so claims stop timing out into
  `nie sprawdzono`.
- Wire the #49 evidence corpus into `verify()` so `citation_correctness` can be measured.
- Tighten the B/C rules in `decide()`, plus Dominik's #30 must-fix (the evidence gap should be
  scoped per `doc_id`, not globally).
- Build the eval fault switch for scenario J (the `simulate` fault is never applied, so J01/J02
  are scored against the live product instead of the fault they're meant to test; FC-J01/FC-J02
  are skipped for the same reason).
- Add gov.pl search as a source.
- `injection_resistance` (0.571 in Run 2) was identical with and without search in that run: it is
  not a retrieval problem, so look at the judge/decide logic instead.

## How the cases were made, and the leakage check (#91)

Cases in `evals/cases.jsonl` were written and labelled from sources, never from our system's answers. The
`source` field names where the label comes from: a fact-check rating, an official page or a quote, usually with the
rating or article date. Exceptions: D01-D04 and H01-H02 are team-made rumours, A12-A15 are verdict-class
definitions, J01/J02 are fault simulations, and FC-I01..I03 were read from a search-engine index, still need a
manual check, and are EUvsDisinfo stand-ins, not the organiser's base.

The `FC-*` cases are not a verified held-out set (UNCONFIRMED). They were written by the same author line as the
judge rules and injection patterns, and `prawdowid/verifier.py` matches FC-E01..E03 phrase for phrase (WORKLOG,
#15: no honest holdout E cases exist). Read `injection_resistance` on FC-E as tuned-on, and treat the FC-I
stand-ins with the caveat above. `FC-*` is a second, differently written slice, not proof of the jury's score.

`tests/test_eval_leakage.py` runs in `make check` and fails when a case input, a quote cited in a `source` field
(word 8-grams over letters and digits, case and punctuation folded; inputs of 4-7 words are compared whole), a case
id or a canary string appears in any file under `prawdowid/` or `frontend/`. Exemption: the web example chips
(`data-example="..."` in `frontend/public/index.html`) deliberately use the organiser's questions (WORKLOG, #16);
only that attribute is skipped. Test fixtures are not scanned, and `input.url` is not checked (no URL case exists).
Before loading the organiser's incident base into `prawdowid/data/`, decide an exemption policy: scenario-I inputs
may legitimately share 8-grams with it. `uv run python -m evals.split_report [results.json]` reads a results file
(default `evals/results/latest.json`) and prints cases, errored cases, accuracy, macro_f1, abstention and median
latency for FC-* and for the rest, with the definitions of `evals.run` (errored calls count as wrong and slow).
Per-case rows carry no cost, citations or canary flags, so the split shows only those metrics; an `FC-*` row of 0
cases means the run did not include them (quick mode).
