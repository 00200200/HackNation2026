# Cost and behaviour under load

This is an extrapolation from a saved test run, not an invoice or a hosting quote.
The only monetary and measured latency inputs below come from
[evals/results/latest.json](../../evals/results/latest.json), timestamp
`2026-11-21T18:19:08+00:00`, product commit
`aa9fb7edceddbc577ca0922c1873ca325129a0bb`, `mode: "quick"`, `n_cases: 8`, `dirty: false`.
The run has `overall_pass: false`; it is not evidence of production quality or capacity.

## Estimate for 1,000 checks

The recorded `metrics.cost_per_100_usd.value` is exactly `1.7199700000000002` USD.
The eval computes a mean of per-answer `cost_usd` and multiplies it by the reporting unit
([evals/run.py:156](../../evals/run.py#L156)). Applying that measured rate:

```text
Estimated USD/check = 1.7199700000000002 / 100 = 0.017199700000000002
Estimated USD for 1,000 checks = 0.017199700000000002 * 1000
                              = 17.199700000000002
Rounded display estimate = USD 17.20 for 1,000 checks
```

This assumes the same request mix and retrieval conditions as the saved run. It prices model
usage, including extraction, rerank and judge, through PydanticAI/genai-prices. Missing usage or
an unpriced/interrupted request can produce `cost_usd: null`; failed calls may still be billed
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
| Google / DuckDuckGo / EUvsDisinfo | [factcheck.py](../../prawdowid/factcheck.py), [websearch.py](../../prawdowid/websearch.py), [euvsdisinfo.py](../../prawdowid/euvsdisinfo.py) | Provider charges and quotas UNCONFIRMED; not included as a measured line item |
| Own store | Local opt-in PostgreSQL, disabled in checks; [compose.yaml](../../compose.yaml), [pipeline.py](../../prawdowid/pipeline.py) | Database operation cost UNCONFIRMED; Supabase is not deployed |

The app has no checkout or user billing path ([frontend](../../frontend/public/index.html),
[API](../../prawdowid/app.py)). That does not establish free hosting, free Discord connectivity
or an ongoing operator subsidy. A free-to-user deployment budget remains UNCONFIRMED.

## Latency and load

Saved `metrics.median_latency_s.value`: exactly `17.00699254195206` seconds
([latest.json](../../evals/results/latest.json)). The eval spaces requests and excludes that wait
from latency ([adapter.py](../../evals/adapter.py)); this is not a concurrency benchmark.
No simultaneous-user capacity, tail latency, saturation point or cost under load is measured:
UNCONFIRMED. We do not extrapolate throughput from this median.

The implemented controls below are configuration, not measured load results. Their numbers come
from the linked code, not from a cost assumption:

- API: `10/minute` per client IP, with HTTP `429` and a Polish notice; outer verification timeout
  `60` seconds ([app.py](../../prawdowid/app.py)). Discord users share the bot's API client IP;
  there is no per-Discord-user quota ([discord_bot.py](../../prawdowid/discord_bot.py)).
- Extraction defaults to `5` claims and `3` queries per checkable claim
  ([verifier.py](../../prawdowid/verifier.py)). Claims and retrieval calls fan out with
  `asyncio.gather` and `asyncio.TaskGroup`; there is no global queue, concurrency semaphore or daily spend cap
  ([pipeline.py](../../prawdowid/pipeline.py)).
- The nominal whole-check budget is `25` seconds, EUvsDisinfo's pipeline cap is `5` seconds and a
  retry needs at least `18` seconds remaining ([pipeline.py](../../prawdowid/pipeline.py)).
  Extraction has a `45` second provider request timeout, but shares the `25` second whole-check
  deadline with URL fetching and claim checks ([verifier.py](../../prawdowid/verifier.py)).
  These are configured cancellation limits, not a measured capacity guarantee.
- Web queries are capped at `10` seconds including retry, page fetches at `8` seconds
  ([websearch.py](../../prawdowid/websearch.py)). Cancellation of a thread-backed search does not
  stop its underlying synchronous work immediately. Slow providers can consume resources after
  the request stops waiting.
- Timeouts or total retrieval failure become `not_checked` with limitations; a provider that
  returns successfully without evidence can lead to `insufficient_evidence`. Missing extraction
  credentials or API failure produces a technical notice, not a factual verdict
  ([pipeline.py](../../prawdowid/pipeline.py), [verifier.py](../../prawdowid/verifier.py)).

Open before a public launch: measure concurrent requests and provider quotas, establish an
operator budget, and test a shared rate limiter across processes. None has a confirmed cost or
capacity figure in this repository.
