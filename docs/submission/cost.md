# Cost and behaviour under load

This is an extrapolation from a saved test run, not an invoice or a hosting quote.
The only monetary and measured latency inputs below come from
[evals/results/latest.json](../../evals/results/latest.json), timestamp
`2026-11-21T19:10:57+00:00`, product commit
`95e6177b5f2ff53f85d222c2cb721630b7b14ebd`, `mode: "quick"`, `n_cases: 9`, `dirty: false`.
The run has `overall_pass: false`; it is not evidence of production quality or capacity. It also
predates PR #40 (this docs change) landing on `main`: no eval has run on the merged commit, by
user decision (`HN_SKIP_EVAL=1`) — a fresh eval on the merged commit is pending.

## Estimate for 1,000 checks

The recorded `metrics.cost_per_100_usd.value` is exactly `1.8220444444444441` USD.
The eval computes a mean of per-answer `cost_usd` over the answers that ran a check (cache hits and
simulated outages are left out) and multiplies it by the reporting unit (`cost_per_100` in
[evals/run.py](../../evals/run.py)). Applying that measured rate:

```text
Estimated USD/check = 1.8220444444444441 / 100 = 0.018220444444444441
Estimated USD for 1,000 checks = 0.018220444444444441 * 1000
                              = 18.220444444444441
Rounded display estimate = USD 18.22 for 1,000 checks
```

This assumes the same request mix and retrieval conditions as the saved run. It prices model
usage, including extraction, rerank and judge, through PydanticAI/genai-prices. `cost_usd` is always a number: the priced sum of the answered requests. A request that was cut,
failed, refused or sent to an unpriced model is counted in `unpriced_requests`, and above 0 the figure
is a lower bound; failed calls may still be billed
([verifier.py](../../prawdowid/verifier.py), [pipeline.py](../../prawdowid/pipeline.py)).
It excludes hosting, network, search/MCP fees, Discord operation and tax; those amounts are
UNCONFIRMED. No price for those services is inferred from a missing API key or a code comment.
The result file contains an aggregate cost metric, not itemised provider invoices.

This is a quick subset, not a full representative workload. The JSON does not record
per-provider retrieval outcomes, model overrides or MCP credentials. Those conditions and costs
with successful page retrieval, different claim counts, retries, different models or all providers
enabled are UNCONFIRMED. Earlier unsuccessful DuckDuckGo retrieval is recorded in
[WORKLOG](../../WORKLOG.md).

## Channel and infrastructure cost

| Component | Confirmed implementation | Cost status |
|---|---|---|
| Web | nginx and static assets call the shared backend; [compose.yaml](../../compose.yaml), [frontend](../../frontend/public/app.js) | Hosting, bandwidth and domain cost UNCONFIRMED |
| Discord | Persistent discord.py bot calls the same API; [discord_bot.py](../../prawdowid/discord_bot.py) | Platform fees, bot hosting and incremental channel cost UNCONFIRMED; no live channel cost measured |
| Verification through either channel | Same API and models, no channel-specific model pipeline; [app.py](../../prawdowid/app.py) | Applying the measured rate to Discord is an assumption; no measured per-channel cost comparison |
| Google / Tavily / EUvsDisinfo | [factcheck.py](../../prawdowid/factcheck.py), [websearch.py](../../prawdowid/websearch.py), [euvsdisinfo.py](../../prawdowid/euvsdisinfo.py) | Tavily: free tier 1,000 credits/month, 1 credit per basic search, observed ~4.9 credits/check on a separate live-key smoke run on an older pipeline (3 queries, a retry in some checks; the current one makes about 4 searches per claim, not re-measured) (the "#7/#8 live proof" entry in [WORKLOG.md](../../WORKLOG.md), not the committed `latest.json`); well inside the free tier for a demo. Google/EUvsDisinfo charges and quotas UNCONFIRMED; none included as a measured `cost_usd` line item |
| Own store | Local opt-in PostgreSQL, disabled in checks; [compose.yaml](../../compose.yaml), [pipeline.py](../../prawdowid/pipeline.py) | Database operation cost UNCONFIRMED; Supabase is not deployed |

The app has no checkout or user billing path ([frontend](../../frontend/public/index.html),
[API](../../prawdowid/app.py)). That does not establish free hosting, free Discord connectivity
or an ongoing operator subsidy. A free-to-user deployment budget remains UNCONFIRMED.

## Latency and load

Saved `metrics.median_latency_s.value`: exactly `3.8964525419287384` seconds
([latest.json](../../evals/results/latest.json)). The eval spaces requests and excludes that wait
from latency ([adapter.py](../../evals/adapter.py)); this is not a concurrency benchmark.
No simultaneous-user capacity, tail latency, saturation point or cost under load is measured:
UNCONFIRMED. We do not extrapolate throughput from this median.

The implemented controls below are configuration, not measured load results. Their numbers come
from the linked code, not from a cost assumption:

- API: `10/minute` per client IP, with HTTP `429` and a Polish notice; outer verification timeout
  `60` seconds ([app.py](../../prawdowid/app.py)). Discord users share the bot's API client IP;
  there is no per-Discord-user quota ([discord_bot.py](../../prawdowid/discord_bot.py)).
- Extraction defaults to `3` checked claims and `2` model queries per checkable claim (plus the claim sentence and one fact-checker-only search, so about `4` Tavily searches per claim)
  ([verifier.py](../../prawdowid/verifier.py)). Claims and retrieval calls fan out with
  `asyncio.gather` and `asyncio.TaskGroup`; there is no global queue, concurrency semaphore or daily spend cap
  ([pipeline.py](../../prawdowid/pipeline.py)).
- The nominal whole-check budget is `40` seconds and EUvsDisinfo's pipeline cap is `5` seconds;
  there is no retry pass ([pipeline.py](../../prawdowid/pipeline.py)).
  Extraction has a `45` second provider request timeout, but shares the `40` second whole-check
  deadline with URL fetching and claim checks ([verifier.py](../../prawdowid/verifier.py)).
  These are configured cancellation limits, not a measured capacity guarantee.
- Web queries are capped at `10` seconds including the provider's retry, page fetches at `8` seconds
  ([websearch.py](../../prawdowid/websearch.py)). Cancellation of a thread-backed search does not
  stop its underlying synchronous work immediately. Slow providers can consume resources after
  the request stops waiting.
- Fact Check sends up to `8` keys per checkable claim at once (`PRAWDOWID_FACTCHECK_MAX_KEYS`),
  each with one retry and a `15` second deadline ([factcheck.py](../../prawdowid/factcheck.py)).
  The claims:search quota is UNCONFIRMED; a key refused for quota is a failed key.
- A timeout makes the claim `not_checked` with limitations and the answer stays `ok`. A failed
  Fact Check (its key for the claim itself, or every key), web search (every query) or (for a
  government claim) gov.pl search does the same when the other evidence is not enough; only when
  every checkable claim ends that way is the answer a technical notice. A failed key or query
  among others that answered is only named in a limitation. A provider that returns successfully without evidence can lead to
  `insufficient_evidence`. Missing extraction credentials or API failure also produce a technical
  notice, not a factual verdict ([pipeline.py](../../prawdowid/pipeline.py),
  [verifier.py](../../prawdowid/verifier.py)).

Open before a public launch: measure concurrent requests and provider quotas, establish an
operator budget, and test a shared rate limiter across processes. None has a confirmed cost or
capacity figure in this repository.
