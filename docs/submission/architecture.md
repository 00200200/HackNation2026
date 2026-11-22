# Architecture and evidence of the current state

This is a submission draft for [issue #18](https://github.com/00200200/HackNation2026/issues/18).
It describes the code on `integration/r2` (2e0f8ce, [PR #109](https://github.com/00200200/HackNation2026/pull/109)).
The saved test results below were measured on `edd34a5`, the last product commit of that branch:
2e0f8ce changes only docs and eval results. This is not a claim of submission readiness.

## Request and evidence flow

```text
Browser: static HTML/CSS/JS -> nginx proxy ---+
                                           +-> FastAPI POST /api/checks -> verify()
Discord /sprawdz -> HTTP, X-Channel: discord +
    -> text, or guarded URL fetch and extraction
    -> claim extraction and search queries (PydanticAI / Anthropic)
    -> each checkable claim in parallel:
         Google Fact Check + EUvsDisinfo MCP + www.gov.pl search + Tavily / allowlisted pages
         + evidence corpus (BM25 over corpus/evidence.jsonl)
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

The API contract is published as an OpenAPI spec: [`docs/openapi.json`](../openapi.json) in the
repository, `/api/openapi.json` on the running service and interactive docs at `/api/docs`. A
new channel sends the same request and needs no verification logic of its own.

The API validates text and HTTP(S) links. The URL path resolves and checks public addresses on
each connection, including redirects, then extracts HTML with trafilatura or PDF text with pypdf.
Social media, access barriers and unsupported files return notices asking for pasted text.
The checked page is excluded as evidence for its own claims. Sources:
[app.py](../../prawdowid/app.py), [link.py](../../prawdowid/link.py),
[verifier.py](../../prawdowid/verifier.py), [rerank.py](../../prawdowid/rerank.py).

Extraction ranks self-contained claims, separates reported speech from its attribution, marks
checkability and writes search queries. Claims run with `asyncio.gather`; retrieval within a claim
uses `asyncio.TaskGroup`, cancelling and awaiting unfinished lookup tasks at the deadline.
Provider threads can finish in the background. Failed providers add limitations. Fact Check sends
several short keys per claim: it counts as failed when the claim's own key or every key failed, and
a failed short key is a limitation only, like one failed web query among several. When Fact Check, every web query or (for a government claim)
the gov.pl search failed and the evidence found is not enough, when all providers failed, or when
the claim deadline expires, the claim is `not_checked`; if every checkable claim ended that way
because of an outage, the answer is a technical error. A provider that answered with no matching
evidence can instead lead to `insufficient_evidence`. The evidence corpus is a file on our own disk,
so it never counts as a source that answered: when every outside source failed, corpus hits count
only if they settle the claim ([corpus_bm25.py](../../prawdowid/corpus_bm25.py)). One extra search with the claim text is allowed if
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
A fact-checker's rating of the checked claim itself, with its rating line verified, maps to a
verdict (`judge.RATINGS`, ADR 0001); a review of another claim is context only.
Sources: [rerank.py](../../prawdowid/rerank.py), [judge.py](../../prawdowid/judge.py),
[factcheck.py](../../prawdowid/factcheck.py), [EUvsDisinfo](../../prawdowid/euvsdisinfo.py).

Incident matching against the organiser's incident base ([PR #38](https://github.com/00200200/HackNation2026/pull/38),
`prawdowid/incidents.py`) is merged into `main`: a match on URL, flagged domain or text similarity
is shown as neutral context next to the claims and never touches the verdict. It is, per the PR's
own title, **shipped empty**: the organiser's incident file has not been shared yet, so the shipped
base has no entries and nothing matches today. The EUvsDisinfo retrieval described above is a
separate, already-populated source and does not substitute for the incident base.

## Models and providers

| Role | Default model ID on `main` | Configuration / source |
|---|---|---|
| Extract claims and queries | `anthropic:claude-sonnet-5-5` (was Opus until 22.11, #88) | `PRAWDOWID_MODEL`, [verifier.py](../../prawdowid/verifier.py) |
| Rerank fragments | `anthropic:claude-haiku-5-5` | `PRAWDOWID_RERANK_MODEL`, [rerank.py](../../prawdowid/rerank.py) |
| Label evidence | `anthropic:claude-sonnet-5-5` | `PRAWDOWID_JUDGE_MODEL`, [judge.py](../../prawdowid/judge.py) |

These are literal code defaults, not a statement about currently available public model names.
Availability is UNCONFIRMED. The saved eval's JSON does not record its models; the results section
below says what it ran on. All model calls use PydanticAI native structured output through the
installed Anthropic provider. Another provider needs its PydanticAI extra (only
`pydantic-ai-slim[anthropic,mcp]` is installed, [pyproject.toml](../../pyproject.toml)), its key
and an image rebuild; none is demonstrated. Compose forwards only `PRAWDOWID_MODEL`, so changing
the rerank or judge model on the server also needs a line in [compose.yaml](../../compose.yaml).
Web search (step 2b) is now **Tavily** (`tavily_search` in `prawdowid/websearch.py`), which
replaced DuckDuckGo (#7, proposed as #20; wired as #45) because DuckDuckGo via `ddgs` returned no
results from our machines and left retrieval empty. Retrieval providers and their terms are listed
in [sources.md](sources.md).

## Deployment, storage and data processing

[Dockerfile](../../Dockerfile) builds the uv backend, runs it as `nobody` and starts uvicorn.
[Frontend Dockerfile](../../frontend/Dockerfile) serves static files with nginx.
[compose.yaml](../../compose.yaml) publishes only the frontend by default, with backend health
checks. The Discord service and local PostgreSQL service are opt-in profiles. Compose now
forwards the extraction model setting, Anthropic key, `GOOGLE_FACTCHECK_API_KEY`,
`TAVILY_API_KEY`, `EUVSDISINFO_API_KEY`, `PRAWDOWID_GOVPL`, `PRAWDOWID_INCIDENTS_PATH` and the
eval-only `PRAWDOWID_EVAL_TOKEN` (unset on the public demo). The check log sits on the `checklog`
volume (`/var/lib/prawdowid`, kept across deploys) and the source cache at a writable `/tmp` path,
both writable for the non-root `nobody` user.

The API runs without PostgreSQL. Step 2c, the own source store, is explicitly disabled in
`pipeline._retrieve`. Its seed-only path uses psycopg, local PostgreSQL, a `simple` full-text index
and prefix terms; no Supabase service, embeddings or vector index is wired on `main`.
The schema stores licence metadata, content hash, publication/retrieval dates and expiry. Deletion
runs when seeding, not on a schedule. Sources: [cache.py](../../prawdowid/cache.py),
[corpus.py](../../prawdowid/corpus.py), [migration](../../db/migrations/001_source_store.sql),
[pipeline.py](../../prawdowid/pipeline.py).

Direct user-linked page bodies are not persisted by the link path. Successful web evidence fetches
are saved to local JSONL as metadata only (full text only once a domain's licence is confirmed,
none today), one record per URL, dropped after 30 days (`RETENTION_DAYS`, `prawdowid/privacy.py`).
Personal data (e-mail, IBAN/NRB, card number, PESEL, ID card and passport number, phone; regex and
checksums, not names or addresses) is masked by `privacy.mask_personal_data` before the text
reaches the extraction model and again in every log line, web search and own-store query (#17,
#39, #82).
Each check is kept 30 days as one masked record in the check log (`prawdowid/checklog.py`), which
the user can delete per session (`DELETE /api/sessions/{id}`, a web button). Input goes to
Anthropic masked (a placeholder keeps the sentence shape so claims still split); masked claim text
and queries go to Google, Tavily and EUvsDisinfo when configured. Details and open gaps (Discord
has no delete command, Docker stdout logs sit outside retention): [docs/privacy.md](../privacy.md).
Browser traffic, fetched evidence, the host and Discord also process data. On this branch
provider processing locations are UNCONFIRMED; a processor table with the providers' own statements
(Anthropic: global routing, storage in the US; Tavily: US; Google Fact Check and EUvsDisinfo: not
stated) is in `docs/privacy.md` of [PR #124](https://github.com/00200200/HackNation2026/pull/124),
not merged yet. Retention agreements are UNCONFIRMED. See [risks.md](risks.md) for code
references and [sources.md](sources.md) for storage limits.

## Default limits, not performance measurements

| Limit | Default | Source |
|---|---|---|
| Input / checked page prefix | 5000 characters | [app.py](../../prawdowid/app.py), [verifier.py](../../prawdowid/verifier.py) |
| Fully considered claims / queries per checkable claim | 3 / 3 | [verifier.py](../../prawdowid/verifier.py) |
| Check budget / API timeout | 40 s / 60 s | [pipeline.py](../../prawdowid/pipeline.py), [app.py](../../prawdowid/app.py) |
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
There is no moderator queue, OCR or reverse image search. The evidence corpus is built and
searched in every check ([corpus.md](../corpus.md)); a live Discord run remains open in
[WORKLOG](../../WORKLOG.md). One URL case (U01) is in the saved quick run; do not present its
latency as a URL benchmark.

## Saved test results and reproduction

Latest tracked result: [evals/results/latest.json](../../evals/results/latest.json), timestamp
`2026-11-22T00:37:27+00:00`, product commit
`edd34a5d2dd7f15515e27f51fa06bc2f1c4b3acb`, `dirty: false`, `mode: "quick"`, `n_cases: 10`,
`concurrency: 4`, `coverage_ok: true`, `overall_pass: false`. Scenarios: `A, B, C, D, E, G, H, I, J, U`;
`E05`/`E06` skipped (no public URL for the fixture page). It ran against the VPS staging stack with
the production keys ([WORKLOG](../../WORKLOG.md), log of 22.11). This is a quick regression run,
one case per scenario, not the full jury-sized evaluation, even though the saved `coverage_ok`
flag is true. The values and targets below are copied exactly from that file; the last column
says how many answers each value rests on:

| Metric | value | target | pass | rests on |
|---|---|---|---|---|
| macro_f1 | 0.2777777777777778 | >= 0.75 | false | the 8 cases with an expected verdict (J01 and U01 have none); 7 of them got `brak wystarczających dowodów` |
| citation_coverage | 1.0 | >= 0.95 | true | claims with a factual verdict only; of the main claims only E01's; per-claim data is not saved |
| citation_correctness | null | >= 0.85 | null | not measured (no `--corpus`) |
| abstention | 1.0 | >= 0.8 | true | 2 cases (D01, H01) |
| injection_resistance | 1.0 | >= 0.9 | true | 1 case (E01, a canary in the pasted text) |
| median_latency_s | 24.877917104000517 | <= 30.0 | true | the first run of each of the 10 cases, 4 in flight |
| end_to_end | 0.9 | >= 1.0 | false | 10 cases; J01 came back `ok` with `nie sprawdzono`, the case expects `technical_error` (#101) |
| channel_consistency | 1.0 | >= 1.0 | true | 1 case (G01); the bot's API client, not Discord; its answer took 0.22 s, from the shared result cache |
| moderator_loop | 0.0 | >= 1.0 | false | 1 case (H01); not built |
| injection_verdict_correct | 1.0 | reported | true | 1 case (E01) |
| cost_per_100_usd | 4.912332 | reported | true | model tokens only, mean over the answers |

`null` means not measured, not passed. Citation coverage counts evidence URL/quote presence for
factual verdicts, not evidence correctness. Citation correctness needs a corpus and would only
test text occurrence, not semantic support; no manual citation spot-check is committed.
Verdict accuracy scores the main claim alone; citation metrics examine all returned claims.
The JSON does not record per-provider retrieval outcomes or model overrides. Extraction ran on
`anthropic:claude-opus-5-5`, the default at `edd34a5`: the message of commit 83d6c65 (#88, on
`integration/r3`) reports a second run on the same commit and stack with only `PRAWDOWID_MODEL`
changed, to Sonnet, and `integration/r3` makes Sonnet the default; that run's JSON is not committed.
Exact reproduction is UNCONFIRMED. Sources: [metrics](../../evals/metrics.py),
[runner](../../evals/run.py), [adapter](../../evals/adapter.py), [WORKLOG](../../WORKLOG.md).

Start the API with `make dev` and configured keys in ignored `.env`. In another terminal:

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick
```

This selects a quick subset of [evals/cases.jsonl](../../evals/cases.jsonl) and overwrites `latest.json`; calls may incur
provider charges. A missing key exercises failure paths, not the saved live conditions. For the
full run, remove `--quick` and add `--corpus corpus/evidence.jsonl` (needed for citation
correctness). The saved run also set `PRAWDOWID_EXTRA_CHANNELS=discord`, which exercises the bot's
API adapter but not Discord transport, and the same `PRAWDOWID_EVAL_TOKEN` on the server and the
runner, which the J cases need; E05/E06 need `PRAWDOWID_FIXTURE_BASE`. Exact live reproduction is
UNCONFIRMED because external results and model versions can change.
