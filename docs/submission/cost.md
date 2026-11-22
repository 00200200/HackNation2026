# Cost and behaviour under load

This is an extrapolation from a saved test run, not an invoice or a hosting quote.
The estimate uses the full run on `ca48b84`, the head of [PR #126](https://github.com/00200200/HackNation2026/pull/126):
[run file](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json), timestamp `2026-11-22T02:27:29+00:00`, recorded commit
`ca48b84390d0df22881024155a37bfafba606ce2`, `mode: "full"`, `n_cases: 75`, `dirty: false`, `overall_pass: false`. It ran extraction, retrieval, rerank and judge. The file is in
PR #128 (`6126ac9`) and PR #123 (`cd61db5`), not on `main` and not in PR #126, so `evals/results/latest.json` in a checkout of
`main` or of PR #126 is a different run. The file does not record the extraction model, the machine or the build of the server under test (its `commit` field is the checkout the harness ran from): UNCONFIRMED.
([architecture.md](architecture.md#saved-test-results-and-reproduction) lists every saved run with a permalink.)

Older runs, not used for the estimate:

- The quick run on `edd34a5` (10 cases, [file](https://github.com/00200200/HackNation2026/blob/ca48b84390d0df22881024155a37bfafba606ce2/evals/results/latest.json), `latest.json` in PR #109 and PR #126): USD 4.91 per 100 checks, extraction
  on Opus (the message of commit `83d6c65` says so; the file does not record the model).
- The quick run on `ca48b84` (10 cases, in PR #123, [file](https://github.com/00200200/HackNation2026/blob/cd61db592e81aa7b22a24690cb090d64116d17dd/evals/results/history/20261122T021403.618691Z-ca48b84-quick.json)): USD 5.54 per 100 checks (about USD 55.39 per
  1,000) and a median of 29.8 s.
- `main` still holds the older run of `2026-11-21T19:10:57+00:00` at commit `95e6177`, `n_cases: 9` ([file](https://github.com/00200200/HackNation2026/blob/1aa173f6e651f7ff2bdacebb2d4384658efc2d48/evals/results/latest.json)).
  It predates the judge, the retrieval pipeline and the check log: its answers came from a stub, so
  its cost (USD 1.82 per 100) and latency (median 3.9 s) cover claim extraction only. Do not quote
  them as the cost of the pipeline ([eval-notes.md](../eval-notes.md)).

The full run has `overall_pass: false` (end-to-end and the moderator loop miss their targets), and its 75 cases are our test set, not
production traffic, so it is not evidence of production quality or capacity. A later commit in PR #126 needs a new run
([#16](https://github.com/00200200/HackNation2026/issues/16)).

## Estimate for 1,000 checks

The recorded `metrics.cost_per_100_usd.value` of the `ca48b84` full run is exactly `4.272704084507042` USD.
The eval takes the mean of `cost_usd` over the first answer of every case that ran a check and multiplies it by 100
(`cost_per_100` in `evals/run.py` at `ca48b84`). It leaves out the product's cache hits (`n_cached_excluded: 0`) and the four cases that
set a simulated fault (`n_simulated_excluded: 4`: `J01`, `J02`, `FC-J01`, `FC-J02`), so the mean runs over `n_priced: 71` answers, with
`n_incomplete: 0`, `n_no_cost: 0` and `lower_bound: false`. The eval assumes that a simulated fault sends no model request. That holds for
`J02`, `FC-J01` and `FC-J02` (0.1 to 0.25 s, status `technical_error`), but `J01` took 23.34 s and returned a full answer, so its model
calls are not priced in the mean (the amount is not recorded: UNCONFIRMED). Applying that measured rate:

```text
Estimated USD/check = 4.272704084507042 / 100 = 0.04272704084507042
Estimated USD for 1,000 checks = 0.04272704084507042 * 1000
                              = 42.72704084507042
Rounded display estimate = USD 42.73 for 1,000 checks
```

This assumes the same request mix and retrieval conditions as the saved run, that is the mix of our 75 test cases, not a measured
production mix. It prices model usage, including extraction, rerank and judge, through PydanticAI/genai-prices. In PR #126
`cost_usd` is always a number and `unpriced_requests` counts the requests that could not be priced
([#102](https://github.com/00200200/HackNation2026/issues/102)), so a total with unpriced requests is a lower bound; failed calls may
still be billed ([verifier.py](../../prawdowid/verifier.py), [pipeline.py](../../prawdowid/pipeline.py)).
It excludes hosting, network, search/MCP fees, Discord operation and tax; those amounts are
UNCONFIRMED. No price for those services is inferred from a missing API key or a code comment.
The result file contains an aggregate cost metric, not itemised provider invoices.

This is a test set, not a representative workload. The JSON does not record per-provider retrieval outcomes, model overrides or MCP
credentials, and not which model extracted the claims. Those conditions and costs
with successful page retrieval, different claim counts, retries, different models or all providers
enabled are UNCONFIRMED. Earlier unsuccessful DuckDuckGo retrieval is recorded in
[WORKLOG](../../WORKLOG.md).

For comparison, the two older ten-case runs cost USD 4.91 (`edd34a5`, Opus) and USD 5.54 (`ca48b84`) per 100 checks. With
Sonnet as the extraction model (the default from #88 in PR #126; `main` still defaults to Opus), the PR #126 description reports about
USD 3.96 per 100 checks (about USD 39.60 per 1,000) and a median of 18.3 s on the ten cases of `edd34a5`. The message of commit `83d6c65`
gives the same comparison with the leading digit of both costs lost (".96 vs .91"). No file of the Sonnet run was saved, so these
figures are UNCONFIRMED.

## Channel and infrastructure cost

| Component | Confirmed implementation | Cost status |
|---|---|---|
| Web | nginx and static assets call the shared backend; [compose.yaml](../../compose.yaml), [frontend](../../frontend/public/app.js) | Hosting, bandwidth and domain cost UNCONFIRMED |
| Discord | Persistent discord.py bot calls the same API; [discord_bot.py](../../prawdowid/discord_bot.py) | Platform fees, bot hosting and incremental channel cost UNCONFIRMED; no live channel cost measured |
| Verification through either channel | Same API and models, no channel-specific model pipeline; [app.py](../../prawdowid/app.py) | Applying the measured rate to Discord is an assumption; no measured per-channel cost comparison |
| Result cache and corpus search | A 30-minute result cache (#59, PR #126) and BM25 search in memory over [corpus/evidence.jsonl](../../corpus/evidence.jsonl), with no model and no network call (#74, PR #126) | No per-check cost of their own. A repeated check inside the cache lifetime makes no model or search call; the share of repeated checks in real traffic is unknown: UNCONFIRMED |
| Google / Tavily / EUvsDisinfo | [factcheck.py](../../prawdowid/factcheck.py), [websearch.py](../../prawdowid/websearch.py), [euvsdisinfo.py](../../prawdowid/euvsdisinfo.py) | Tavily: free tier 1,000 credits/month, 1 credit per basic search, observed ~4.9 credits/check on a separate live-key smoke run before this branch merged onto `main` (the "#7/#8 live proof" entry in [WORKLOG.md](../../WORKLOG.md), not a committed run file); well inside the free tier for a demo. The query count of the current pipeline (up to 3 claims, 3 queries each, plus a retry search) was not measured: UNCONFIRMED. A query repeated within 24 hours is answered from our cache and spends no credit (#110, PR #126; the saving is not measured). Google/EUvsDisinfo charges and quotas UNCONFIRMED (PR #126 sends up to 8 Fact Check queries per claim, #100); none included as a measured `cost_usd` line item |
| Own store | Local opt-in PostgreSQL, disabled in checks; [compose.yaml](../../compose.yaml), [pipeline.py](../../prawdowid/pipeline.py) | Database operation cost UNCONFIRMED; Supabase is not deployed |

The app has no checkout or user billing path ([frontend](../../frontend/public/index.html),
[API](../../prawdowid/app.py)). That does not establish free hosting, free Discord connectivity
or an ongoing operator subsidy. A free-to-user deployment budget remains UNCONFIRMED.

## Latency and load

The `ca48b84` full run's `metrics.median_latency_s.value` is exactly `17.842587917002675` seconds,
against a target of at most 30 seconds ([run file](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json)). It covers the whole pipeline
(extraction, retrieval, rerank, judge), takes the first run of each of the 75 cases and leaves cache hits out (none of the first runs
was one). 8 of the 75 answers took more than 30 s and the slowest, `D03`, took 38.57 s; the file records no percentile.
The two URL cases, `U01` (a long gov.pl page from #63) and `U02`, took 28.47 s and 27.8 s. The eval spaces requests at least `PRAWDOWID_MIN_INTERVAL_S`
(6.5 s by default) apart and excludes that wait from latency ([adapter.py](../../evals/adapter.py));
the file records `concurrency: 4`. This is a regression run at concurrency 4, not a concurrency benchmark.
No simultaneous-user capacity, tail latency, saturation point or cost under load is measured:
UNCONFIRMED. We do not extrapolate throughput from this median. The older run on `main` reports
3.8964525419287384 seconds, which is claim extraction only. The quick run on `ca48b84` in PR #123 reports a median of
29.8 s over ten cases ([file](https://github.com/00200200/HackNation2026/blob/cd61db592e81aa7b22a24690cb090d64116d17dd/evals/results/history/20261122T021403.618691Z-ca48b84-quick.json)), 0.2 s under the 30 s target.

The implemented controls below are configuration, not measured load results. Their numbers come
from the linked code (PR #126 at `ca48b84`, unless a bullet names `main`), not from a cost assumption:

- API: `10/minute` per client IP, with HTTP `429` and a Polish notice; outer verification timeout
  `60` seconds ([app.py](../../prawdowid/app.py)). Discord users share the bot's API client IP;
  there is no per-Discord-user quota ([discord_bot.py](../../prawdowid/discord_bot.py)).
- Extraction defaults to `3` claims (`5` on `main`) and `3` queries per checkable claim
  ([verifier.py](../../prawdowid/verifier.py)). Claims and retrieval calls fan out with
  `asyncio.gather` and `asyncio.TaskGroup`; there is no global queue, concurrency semaphore or daily spend cap
  ([pipeline.py](../../prawdowid/pipeline.py)).
- The nominal whole-check budget is `40` seconds (`PRAWDOWID_CHECK_BUDGET_S`; `25` on `main`),
  EUvsDisinfo's pipeline cap is `5` seconds, the corpus search cap is `5` seconds (#74, PR #126) and a
  retry needs at least `18` seconds remaining ([pipeline.py](../../prawdowid/pipeline.py)).
  Extraction has a `45` second provider request timeout, rerank `10` and the judge `20`, each with
  one retry; extraction shares the `40` second whole-check deadline with URL fetching and claim
  checks ([verifier.py](../../prawdowid/verifier.py), [judge.py](../../prawdowid/judge.py),
  [rerank.py](../../prawdowid/rerank.py)).
  These are configured cancellation limits, not a measured capacity guarantee.
- Fact Check (PR #126, #100): each request times out after `8` seconds, the lookups for one claim stop
  after `15` seconds, a request is tried at most twice, and a claim gets up to `8` queries
  ([factcheck.py](../../prawdowid/factcheck.py)). The `claims:search` quota is UNCONFIRMED.
- Web queries are capped at `10` seconds including retry, page fetches at `8` seconds
  ([websearch.py](../../prawdowid/websearch.py)). Cancellation of a thread-backed search does not
  stop its underlying synchronous work immediately. Slow providers can consume resources after
  the request stops waiting.
- A timeout makes the claim `not_checked` with limitations and the answer stays `ok`. In PR #126 a
  failed Fact Check, web search or (for a government claim) gov.pl search does the same when the other
  evidence is not enough, and only when every checkable claim ends that way is the answer a technical
  notice. Fact Check counts as failed when the query with the claim itself or all its queries failed
  (#100). On `main` a failure of some sources with nothing found from the rest gives
  `insufficient_evidence`, and `not_checked` comes only from the time limit, a judge outage or all
  sources failing, with the answer staying `ok` (#60). A provider that returns successfully without
  evidence can lead to `insufficient_evidence`. Missing extraction credentials or API failure also produce a technical
  notice, not a factual verdict ([pipeline.py](../../prawdowid/pipeline.py),
  [verifier.py](../../prawdowid/verifier.py)).
- A repeated check of the same text within 30 minutes is answered from the result cache without a
  model or search call (#59, PR #126). A repeated web query within 24 hours is answered from the
  search cache (#110, PR #126, `PRAWDOWID_SEARCH_CACHE_TTL_S`).

Open before a public launch: measure concurrent requests and provider quotas, establish an
operator budget, and test a shared rate limiter across processes. None has a confirmed cost or
capacity figure in this repository.
