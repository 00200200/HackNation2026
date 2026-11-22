| timestamp | sha | mode | cases | macro_f1 | abstention | injection | e2e | channel | median s | cost/100 | overall | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ~2026-11-?? (before Tavily) | unknown | quick | 8 | 0.250 | 1.000 | 1.000 | 0.875 | — | ~15 | 1.65 | FAIL | RECONSTRUCTED, no JSON; pre-Tavily smoke test. See docs/eval-notes.md. |
| 2026-11-21T19:10:57+00:00 | 95e6177 | quick | 9 | 0.100 | 1.000 | 0.000 | 0.889 | — | 3.90 | 1.82 | FAIL | Real data, but of the pre-judge stub (the verifier returned a constant abstention, so abstention is a constant and time and cost cover extraction only; see docs/eval-notes.md), from the committed `evals/results/latest.json` (predates this history mechanism, so backfilled here too). FC-J01/FC-J02 skipped. |
| 2026-11-21 (same commit as next row) | 8c6f396 | — | — | 0.353 | 1.000 | 0.571 | 0.972 | 1.000 | 5.8 | — | FAIL | RECONSTRUCTED, no JSON; "Run 1", invalid (no TAVILY/EUVSDISINFO keys, only Fact Check searched). mode/cases UNCONFIRMED. See docs/eval-notes.md. |
| 2026-11-21 ~20:44 UTC | 8c6f396 | full | 71 | 0.498 | 0.583 | 0.571 | 0.704 | 0.000 | 18.2 | — | FAIL | RECONSTRUCTED, no JSON; "Run 2". Distorted by Anthropic timeouts (FC-A02+) and a 25s CHECK_BUDGET_S; not a quality signal for FC-*. See docs/eval-notes.md. |
| 2026-11-22T00:37:27+00:00 | edd34a5 | quick | 10 | 0.278 | 1.000 | 1.000 | 0.900 | 1.000 | 24.9 | 4.91 | FAIL |  |
| 2026-11-22T02:15:53+00:00 | ca48b84 | quick | 10 | 0.750 | 1.000 | 1.000 | 0.900 | 1.000 | 29.8 | 5.54 | FAIL |  |
| 2026-11-22T02:27:29+00:00 | ca48b84 | full | 75 | 0.803 | 0.917 | 1.000 | 0.973 | 1.000 | 17.8 | 4.27 | FAIL |  |
| 2026-11-22T04:10:21+00:00 | b849802 | quick | 10 | 0.783 | 1.000 | 1.000 | 0.900 | 1.000 | 26.6 | >=4.97 | FAIL |  |
| 2026-11-22T04:42:07+00:00 | af7ec13 | full | 75 | 0.823 | 0.750 | 1.000 | 0.973 | 1.000 | 15.1 | 3.48 | FAIL |  |
