# Cost and behaviour under load

This is an extrapolation from a saved test run, not an invoice or a hosting quote.
The only monetary and measured latency inputs below come from
[evals/results/latest.json](../../evals/results/latest.json), timestamp
`2026-11-22T00:37:27+00:00`, product commit
`edd34a5d2dd7f15515e27f51fa06bc2f1c4b3acb`, `mode: "quick"`, `n_cases: 10`, `concurrency: 4`,
`dirty: false`. It ran against the VPS staging stack with the production keys and the code
defaults of that commit, so claim extraction ran on Claude Opus (see
[architecture.md](architecture.md#saved-test-results-and-reproduction)). The run has
`overall_pass: false`; it is not evidence of production quality or capacity.

## Estimate for 1,000 checks

The recorded `metrics.cost_per_100_usd.value` is exactly `4.912332` USD. The runner at
`edd34a5` took the mean of the per-answer `cost_usd` of the first answer of each case and
multiplied it by 100 (`cost_per_100_usd` in [evals/run.py](../../evals/run.py)). It reports no
cost when any answer lacks a price, so every answer of this run was priced. `integration/r3`
leaves cache hits and simulated outages out of that mean and counts unpriced requests instead
(#101); this run predates that. Applying the measured rate:

```text
Estimated USD/check = 4.912332 / 100 = 0.04912332
Estimated USD for 1,000 checks = 0.04912332 * 1000
                              = 49.12332
Rounded display estimate = USD 49.12 for 1,000 checks
```

This assumes the same request mix and retrieval conditions as the saved run: ten quick cases, one
of them a link. It prices model usage, including extraction, rerank and judge, through
PydanticAI/genai-prices. On `integration/r3`, `cost_usd` is always a number: the priced sum of the
answered requests. A request that was cut, failed, refused or sent to an unpriced model is counted
in `unpriced_requests`, and above 0 the figure is a lower bound; failed calls may still be billed
([verifier.py](../../prawdowid/verifier.py), [pipeline.py](../../prawdowid/pipeline.py)).
`integration/r3` makes Sonnet the extraction default
(#88); its commit message reports $3.96 per 100 checks on the same quick set, but that run's JSON
is not committed, so it is not used here.

It excludes hosting, network, search fees, Discord operation and tax. Web search is the one fee
with recorded inputs, both older than this run: about 4.9 Tavily credits per check in an 8-case
run before the merge onto `main` (the "#7/#8 live proof" entry in [WORKLOG.md](../../WORKLOG.md)),
and pay-as-you-go at $0.008 a credit (the #7 provider research in the same file). At that rate
1,000 checks would take about 4,900 credits, roughly $39, or $31 after the 1,000 free monthly
credits: UNCONFIRMED for the current code, where the model is asked for three web queries for
each of up to three checked claims and a claim can get one more search on retry. Google Fact
Check, EUvsDisinfo and the www.gov.pl search have no recorded fee; their quotas are UNCONFIRMED.
The result file contains an aggregate cost metric, not itemised provider invoices.

This is a quick subset, not a full representative workload. The JSON does not record
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

Saved `metrics.median_latency_s.value`: exactly `24.877917104000517` seconds
([latest.json](../../evals/results/latest.json)), over the first answer of each of the ten cases,
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
- Extraction checks at most `3` claims in full and asks for `3` web queries per checkable claim
  ([verifier.py](../../prawdowid/verifier.py)). Claims and retrieval calls fan out with
  `asyncio.gather` and `asyncio.TaskGroup`; there is no global queue or daily spend cap, only
  per-process limits on page extraction and gov.pl requests ([pipeline.py](../../prawdowid/pipeline.py),
  [link.py](../../prawdowid/link.py), [govpl.py](../../prawdowid/govpl.py)).
- The whole-check budget is `40` seconds, EUvsDisinfo and the corpus lookup are capped at `5`
  seconds each in the pipeline and a retry needs at least `18` seconds remaining
  ([pipeline.py](../../prawdowid/pipeline.py)). Extraction has a `45` second provider request
  timeout, but shares the `40` second whole-check deadline with URL fetching and claim checks
  ([verifier.py](../../prawdowid/verifier.py)). These are configured cancellation limits, not a
  measured capacity guarantee.
- Web queries are capped at `10` seconds including retry, page fetches at `8` seconds
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
