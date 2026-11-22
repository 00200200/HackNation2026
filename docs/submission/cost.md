# Cost and behaviour under load

This is an extrapolation from a saved test run, not an invoice or a hosting quote.
The only monetary and measured latency inputs below come from
[evals/results/latest.json](../../evals/results/latest.json) (the same file as
`evals/results/history/20261122T021757.182695Z-ca48b84-full.json`), timestamp
`2026-11-22T02:27:29+00:00`, commit `ca48b84390d0df22881024155a37bfafba606ce2` (`integration/r3`),
`mode: "full"`, `n_cases: 75`, `concurrency: 4`, `dirty: false`. The commit is the eval harness's;
which server and code version answered is not recorded (see
[architecture.md](architecture.md#saved-test-results-and-reproduction)). At that commit the code
default extracts claims with Claude Sonnet (#88). The run has `overall_pass: false`; it is not
evidence of production quality or capacity.

## Estimate for 1,000 checks

The recorded `metrics.cost_per_100_usd.value` is exactly `4.272704084507042` USD: the mean of the
per-answer `cost_usd` of the first answer of each case, times 100 (`cost_per_100` in
[evals/run.py](../../evals/run.py)). It rests on 71 priced answers (`n_priced`); the 4 simulated
outages (J01, J02, FC-J01, FC-J02) send no model request and are left out
(`n_simulated_excluded`), no first answer came from the result cache (`n_cached_excluded: 0`) and
none had unpriced requests (`n_incomplete: 0`, `lower_bound: false`). Applying the measured rate:

```text
Estimated USD/check = 4.272704084507042 / 100 = 0.04272704084507042
Estimated USD for 1,000 checks = 0.04272704084507042 * 1000
                              = 42.72704084507042
Rounded display estimate = USD 42.73 for 1,000 checks
```

This assumes the same request mix and retrieval conditions as the saved run: our 75 cases, two of
them links. It prices model usage, including extraction, rerank and judge, through
PydanticAI/genai-prices. On `integration/r3`, `cost_usd` is always a number: the priced sum of the
answered requests. A request that was cut, failed, refused or sent to an unpriced model is counted
in `unpriced_requests`, and above 0 the figure is a lower bound; failed calls may still be billed
([verifier.py](../../prawdowid/verifier.py), [pipeline.py](../../prawdowid/pipeline.py)).
The earlier quick run on `edd34a5` (10 cases, Opus extraction) recorded $4.91 per 100 checks
([HISTORY.md](../../evals/results/HISTORY.md)); it is not used here.

It excludes hosting, network, search fees, Discord operation and tax. Web search is the one fee
with recorded inputs, both older than this run: about 4.9 Tavily credits per check in an 8-case
run before the merge onto `main` (the "#7/#8 live proof" entry in [WORKLOG.md](../../WORKLOG.md)),
and pay-as-you-go at $0.008 a credit (the #7 provider research in the same file). At that rate
1,000 checks would take about 4,900 credits, roughly $39, or $31 after the 1,000 free monthly
credits: UNCONFIRMED for the current code, where the model is asked for three web queries for
each of up to three checked claims and a claim can get one more search on retry. Google Fact
Check, EUvsDisinfo and the www.gov.pl search have no recorded fee; their quotas are UNCONFIRMED.
The result file contains an aggregate cost metric, not itemised provider invoices.

The case mix is our test set, not a sample of real traffic. The JSON does not record
per-provider retrieval outcomes, model overrides or MCP credentials. Costs with different claim
counts, retries, different models or all providers succeeding are UNCONFIRMED.

## Channel and infrastructure cost

| Component | Confirmed implementation | Cost status |
|---|---|---|
| Web | nginx and static assets call the shared backend; [compose.yaml](../../compose.yaml), [frontend](../../frontend/public/app.js) | Hosting, bandwidth and domain cost UNCONFIRMED |
| Discord | Persistent discord.py bot calls the same API; [discord_bot.py](../../prawdowid/discord_bot.py). Not running on the server and never run against real Discord ([deploy.md](../deploy.md), section 7) | Platform fees, bot hosting and incremental channel cost UNCONFIRMED; no live channel cost measured |
| Verification through either channel | Same API and models, no channel-specific model pipeline; [app.py](../../prawdowid/app.py) | Applying the measured rate to Discord is an assumption; no measured per-channel cost comparison |
| Google / Tavily / EUvsDisinfo / www.gov.pl | [factcheck.py](../../prawdowid/factcheck.py), [websearch.py](../../prawdowid/websearch.py), [euvsdisinfo.py](../../prawdowid/euvsdisinfo.py), [govpl.py](../../prawdowid/govpl.py) | Tavily: estimate above, UNCONFIRMED. The others: charges and quotas UNCONFIRMED. None is a measured `cost_usd` line item |
| Own store | Local opt-in PostgreSQL, disabled in checks; [compose.yaml](../../compose.yaml), [pipeline.py](../../prawdowid/pipeline.py) | Database operation cost UNCONFIRMED; Supabase is not deployed |

The app has no checkout or user billing path ([frontend](../../frontend/public/index.html),
[API](../../prawdowid/app.py)). That does not establish free hosting, free Discord connectivity
or an ongoing operator subsidy. A free-to-user deployment budget remains UNCONFIRMED.

## Latency and load

Saved `metrics.median_latency_s.value`: exactly `17.842587917002675` seconds
([latest.json](../../evals/results/latest.json)), over the first answer of each of the 75 cases,
with up to four cases in flight. By default the eval starts requests at least 6.5 s apart and
excludes that wait from latency ([adapter.py](../../evals/adapter.py)); this is not a concurrency benchmark.
No simultaneous-user capacity, tail latency, saturation point or cost under load is measured:
UNCONFIRMED. We do not extrapolate throughput from this median.

The implemented controls below are configuration, not measured load results. Their numbers come
from the linked code, not from a cost assumption:

- API: `10/minute` per client IP, with HTTP `429` and a Polish notice; outer verification timeout
  `60` seconds ([app.py](../../prawdowid/app.py)). Discord users share the bot's API client IP;
  there is no per-Discord-user quota ([discord_bot.py](../../prawdowid/discord_bot.py)).
- The same input within 30 minutes gets the stored answer from a per-process result cache (at
  most 500 answers), with no model or search calls, whichever channel asks
  ([app.py](../../prawdowid/app.py)).
- Extraction checks at most `3` claims in full and asks for `2` model queries per checkable claim,
  plus the claim sentence and one fact-checker-only search, so about `4` Tavily searches per claim
  ([verifier.py](../../prawdowid/verifier.py)). Claims and retrieval calls fan out with
  `asyncio.gather` and `asyncio.TaskGroup`; there is no global queue or daily spend cap, only
  per-process limits on page extraction and gov.pl requests ([pipeline.py](../../prawdowid/pipeline.py),
  [link.py](../../prawdowid/link.py), [govpl.py](../../prawdowid/govpl.py)).
- The whole-check budget is `40` seconds, EUvsDisinfo and the corpus lookup are capped at `5`
  seconds each in the pipeline, and there is no second search pass
  ([pipeline.py](../../prawdowid/pipeline.py)). Extraction has a `45` second provider request
  timeout, but shares the `40` second whole-check deadline with URL fetching and claim checks
  ([verifier.py](../../prawdowid/verifier.py)). These are configured cancellation limits, not a
  measured capacity guarantee.
- Web queries are capped at `10` seconds including the provider's retry, page fetches at `8` seconds
  ([websearch.py](../../prawdowid/websearch.py)), the gov.pl search at `10` seconds
  ([govpl.py](../../prawdowid/govpl.py)) and Fact Check at `15` seconds
  ([factcheck.py](../../prawdowid/factcheck.py)). Cancellation of a thread-backed search does not
  stop its underlying synchronous work immediately. Slow providers can consume resources after
  the request stops waiting.
- Fact Check sends up to `8` keys per checkable claim at once (`PRAWDOWID_FACTCHECK_MAX_KEYS`),
  each with one retry and a `15` second deadline ([factcheck.py](../../prawdowid/factcheck.py)).
  The claims:search quota is UNCONFIRMED; a key refused for quota is a failed key.
- A claim cut by the deadline before its sources and judge answered is `not_checked` with
  limitations and the answer stays `ok`. A failed Fact Check (its key for the claim itself, or every
  key), web search (every query) or (for a government claim) gov.pl search does the same when the
  other evidence is not enough; when every checkable claim ends that way because of an outage, the
  answer is a technical notice. A failed key or query among others that answered is only named in a
  limitation. A provider that returns successfully without evidence can lead to
  `insufficient_evidence`. Missing extraction credentials or API failure also produce a technical
  notice, not a factual verdict ([pipeline.py](../../prawdowid/pipeline.py),
  [verifier.py](../../prawdowid/verifier.py)).

Open before a public launch: measure concurrent requests and provider quotas, establish an
operator budget, and test a shared rate limiter across processes. None has a confirmed cost or
capacity figure in this repository.
