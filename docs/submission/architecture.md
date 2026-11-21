# Architecture and evidence of the current state

This is a submission draft for [issue #18](https://github.com/00200200/HackNation2026/issues/18).
The implementation inspected is the `LukiLenkiewicz/issue11-fanout` stack at `cacfb4e`;
the measured product commit is identified below. This is not a claim of submission readiness.

## Request and evidence flow

```text
Browser: static HTML/CSS/JS -> nginx proxy ---+
                                           +-> FastAPI POST /api/checks -> verify()
Discord /sprawdz -> HTTP, X-Channel: discord +
    -> text, or guarded URL fetch and extraction
    -> claim extraction and search queries (PydanticAI / Anthropic)
    -> each checkable claim in parallel:
         Google Fact Check + EUvsDisinfo MCP + DuckDuckGo / allowlisted pages
         -> deduplicate and rerank fragments -> label and validate quotes
         -> judge.decide() -> shared CheckResult -> channel rendering

Web retrieval -> local corpus/docs.jsonl cache (successful fetches)
Manual seed -> PostgreSQL documents/chunks (disabled in the check pipeline)
```

The browser posts JSON on the same origin and renders text using DOM `textContent`, with
separate quote, premise and limitation sections. nginx proxies the API and sets a Content Security
Policy. Discord has no separate verification logic; it renders the shared contract, escapes
Markdown and mentions, suppresses previews and marks truncation. Its replies are not ephemeral,
so their visibility depends on the Discord channel. Sources:
[frontend app](../../frontend/public/app.js), [HTML](../../frontend/public/index.html),
[styles](../../frontend/public/styles.css), [nginx](../../frontend/nginx.conf),
[Discord](../../prawdowid/discord_bot.py), [contract](../../prawdowid/contract.py).

The API validates text and HTTP(S) links. The URL path resolves and checks public addresses on
each connection, including redirects, then extracts HTML with trafilatura or PDF text with pypdf.
Social media, access barriers and unsupported files return notices asking for pasted text.
The checked page is excluded as evidence for its own claims. Sources:
[app.py](../../prawdowid/app.py), [link.py](../../prawdowid/link.py),
[verifier.py](../../prawdowid/verifier.py), [rerank.py](../../prawdowid/rerank.py).

Extraction ranks self-contained claims, separates reported speech from its attribution, marks
checkability and writes search queries. Claims run with `asyncio.gather`; retrieval within a claim
uses `asyncio.TaskGroup`, cancelling and awaiting unfinished lookup tasks at the deadline.
Provider threads can finish in the background. Failed providers add limitations; when all retrieval providers fail or the claim
deadline expires, the claim is `not_checked`. An available provider returning no matching evidence
can instead lead to `insufficient_evidence`. One extra search with the claim text is allowed if
enough time remains. Sources: [verifier.py](../../prawdowid/verifier.py),
[pipeline.py](../../prawdowid/pipeline.py).

The reranker canonicalises URLs, removes repeated and near-identical fragments and interleaves
documents before ranking. The judge model labels each fragment as supporting, refuting or
contextual evidence. Code checks the quoted span against the retrieved title/fragment, then
`judge.decide()` applies the verdict rules. One `official`, `primary` or `fact_check` source with
validated evidence, or two independent origins, can be sufficient; conflicts lead to abstention.
These thresholds are code policy, not measured guarantees. A domain alone does not determine
truth. EUvsDisinfo matches are context only, including those returned through Google: the
pipeline normalises their type to `disinfo_database`, which cannot decide a verdict on its own.
Fact Check returns
review metadata with no full review passage; the title may be the only quoted text available.
Sources: [rerank.py](../../prawdowid/rerank.py), [judge.py](../../prawdowid/judge.py),
[factcheck.py](../../prawdowid/factcheck.py), [EUvsDisinfo](../../prawdowid/euvsdisinfo.py).

Incident matching and a separate incident warning are pending in
[PR #38](https://github.com/00200200/HackNation2026/pull/38), not shipped in this branch.
The EUvsDisinfo retrieval described here does not establish that feature as delivered.

## Models and providers

| Role | Default model ID in this branch | Configuration / source |
|---|---|---|
| Extract claims and queries | `anthropic:claude-opus-5-5` | `PRAWDOWID_MODEL`, [verifier.py](../../prawdowid/verifier.py) |
| Rerank fragments | `anthropic:claude-haiku-5-5` | `PRAWDOWID_RERANK_MODEL`, [rerank.py](../../prawdowid/rerank.py) |
| Label evidence | `anthropic:claude-sonnet-5-5` | `PRAWDOWID_JUDGE_MODEL`, [judge.py](../../prawdowid/judge.py) |

These are literal code defaults, not a statement about currently available public model names.
Availability and the model overrides used in the saved eval are UNCONFIRMED: its JSON does not
record them. All model calls use PydanticAI native structured output through the installed
Anthropic provider. Alternative provider dependencies and credentials are not demonstrated.
Retrieval providers and their terms are listed in [sources.md](sources.md).

## Deployment, storage and data processing

[Dockerfile](../../Dockerfile) builds the uv backend, runs it as `nobody` and starts uvicorn.
[Frontend Dockerfile](../../frontend/Dockerfile) serves static files with nginx.
[compose.yaml](../../compose.yaml) publishes only the frontend by default, with backend health
checks. The Discord service and local PostgreSQL service are opt-in profiles. Compose forwards
the extraction model setting and Anthropic key, but not the optional retrieval keys or most
tuning variables. The [README run instructions](../../README.md#run) show an override for the
retrieval keys. The backend image has no writable cache directory prepared for `nobody`; a
successful page retrieval can fail to save and become a retrieval limitation in this Docker path
([cache.py](../../prawdowid/cache.py), [pipeline.py](../../prawdowid/pipeline.py)).

The API runs without PostgreSQL. Step 2c, the own source store, is explicitly disabled in
`pipeline._retrieve`. Its seed-only path uses psycopg, local PostgreSQL, a `simple` full-text index
and prefix terms; no Supabase service, embeddings or vector index is wired in this branch.
The schema stores licence metadata, content hash, publication/retrieval dates and expiry. Deletion
runs when seeding, not on a schedule. Sources: [cache.py](../../prawdowid/cache.py),
[corpus.py](../../prawdowid/corpus.py), [migration](../../db/migrations/001_source_store.sql),
[pipeline.py](../../prawdowid/pipeline.py).

Direct user-linked page bodies are not persisted by the link path. Successful web evidence fetches
are saved to local JSONL; there is no cache expiry or refresh of an existing URL. Stdout logs
include claim text and results, and link URLs/hashes, without a deletion policy. Raw input goes
to Anthropic; claim text goes to Google and EUvsDisinfo when configured. Only web search queries
are masked by `privacy.mask_personal_data`. Browser traffic, fetched evidence, the host and Discord
also process data. Exact provider processing locations and retention agreements are UNCONFIRMED.
See [risks.md](risks.md) for code references and [sources.md](sources.md) for storage limits.

## Default limits, not performance measurements

| Limit | Default | Source |
|---|---|---|
| Input / checked page prefix | 5000 characters | [app.py](../../prawdowid/app.py), [verifier.py](../../prawdowid/verifier.py) |
| Fully considered claims / queries per checkable claim | 5 / 3 | [verifier.py](../../prawdowid/verifier.py) |
| Check budget / API timeout | 25 s / 60 s | [pipeline.py](../../prawdowid/pipeline.py), [app.py](../../prawdowid/app.py) |
| Extraction call timeout | 45 s provider setting, bounded by the shared check deadline | [verifier.py](../../prawdowid/verifier.py) |
| Web query / whole page fetch budget | 10 s / 8 s | [websearch.py](../../prawdowid/websearch.py) |
| Link fetch | 10 s, 3 redirects, `2 * 1024 * 1024` bytes | [link.py](../../prawdowid/link.py) |
| Evidence fragments: size / candidates / retained | 800 characters / 60 / 12 | [rerank.py](../../prawdowid/rerank.py) |
| Requests per client IP | 10/minute; the bot shares its IP across users | [app.py](../../prawdowid/app.py), [Discord client](../../prawdowid/discord_bot.py) |
| Discord response cap | 5 messages of 2000 characters, with truncation notice | [discord_bot.py](../../prawdowid/discord_bot.py) |

Extraction and URL fetching share the check deadline. A cut extraction returns a technical notice;
unfinished claims return `not_checked`. A judge outage also maps to `not_checked`; a retry judge
failure can preserve the first-pass assessment with a limitation when first-pass candidates existed.
Request deadlines
do not establish server capacity; [cost.md](cost.md) describes the unmeasured load behaviour.
There is no moderator queue, OCR or reverse image search. The demo corpus and live Discord run
remain open in [WORKLOG](../../WORKLOG.md). URL inputs are not exercised by the saved eval set
([cases](../../evals/cases.jsonl)); do not present its latency as a URL benchmark.

## Saved test results and reproduction

Latest tracked result: [evals/results/latest.json](../../evals/results/latest.json), timestamp
`2026-11-21T18:19:08+00:00`, product commit
`aa9fb7edceddbc577ca0922c1873ca325129a0bb`, `dirty: false`, `mode: "quick"`, `n_cases: 8`,
`coverage_ok: true`, `overall_pass: false`. Scenarios: `A, B, C, D, E, G, I, J`.
This is a quick regression run, not the full jury-sized evaluation, even though the saved
`coverage_ok` flag is true. The following values and targets are copied exactly from that file:

| Metric | value | target | pass |
|---|---|---|---|
| macro_f1 | 0.25 | >= 0.75 | false |
| citation_coverage | 1.0 | >= 0.95 | true |
| citation_correctness | null | >= 0.85 | null |
| abstention | 1.0 | >= 0.8 | true |
| injection_resistance | 1.0 | >= 0.9 | true |
| median_latency_s | 17.00699254195206 | <= 30.0 | true |
| end_to_end | 0.875 | >= 1.0 | false |
| channel_consistency | null | >= 1.0 | null |
| cost_per_100_usd | 1.7199700000000002 | reported | true |

`null` means not measured, not passed. Citation coverage counts evidence URL/quote presence for
factual verdicts, not evidence correctness. Citation correctness needs a corpus and would only
test text occurrence, not semantic support; no manual citation spot-check is committed.
Verdict accuracy scores the main claim alone; citation metrics examine all returned claims.
Scenario J failures were not forced by an eval switch. The worklog records Anthropic and Google
keys for this quick run and unsuccessful DuckDuckGo retrieval in an earlier full run. The latest
JSON does not record per-provider retrieval outcomes or model overrides; those conditions are
UNCONFIRMED for exact reproduction. Sources: [metrics](../../evals/metrics.py),
[runner](../../evals/run.py), [adapter](../../evals/adapter.py), [WORKLOG](../../WORKLOG.md).

Start the API with `make dev` and configured keys in ignored `.env`. In another terminal:

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick
```

This selects a quick subset of [evals/cases.jsonl](../../evals/cases.jsonl) and overwrites `latest.json`; calls may incur
provider charges. A missing key exercises failure paths, not the saved live conditions. Once a
licensed corpus exists, remove `--quick` and add `--corpus corpus/docs.jsonl` for the full run.
To exercise the bot's API adapter, add
`PRAWDOWID_EXTRA_CHANNELS=discord`; this does not test Discord transport itself. Exact live
reproduction is UNCONFIRMED because external results and model versions can change.
