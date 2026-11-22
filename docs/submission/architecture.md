# Architecture and evidence of the current state

This is a submission draft for [issue #18](https://github.com/00200200/HackNation2026/issues/18).
It was first written for `integration/r2` (2e0f8ce, [PR #109](https://github.com/00200200/HackNation2026/pull/109));
the model table and the Fact Check route follow `integration/r3` (ca48b84, #88, #100). The saved test
results below are the full run on a14b93c plus a separate E05-E15 run on 5e5be00; the earlier full run
on ca48b84 and the quick run on `edd34a5` stay in [HISTORY.md](../../evals/results/HISTORY.md). This is not a claim of submission readiness.

## Request and evidence flow

```text
Browser: static HTML/CSS/JS -> nginx proxy ---+
                                           +-> FastAPI POST /api/checks -> verify()
Discord /sprawdz -> HTTP, X-Channel: discord +
    -> text, or guarded URL fetch and extraction
    -> claim extraction and search queries (PydanticAI / Anthropic)
    -> each checkable claim in parallel:
         Google Fact Check + EUvsDisinfo MCP + www.gov.pl search + Perplexity (Tavily fallback) / allowlisted pages
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
only if they settle the claim ([corpus_bm25.py](../../prawdowid/corpus_bm25.py)). There is no second search pass: the first pass already searches the claim
sentence and, separately, the fact-checkers' domains only, in parallel with the model's queries. Sources: [verifier.py](../../prawdowid/verifier.py),
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

| Role | Default model ID on `integration/r3` | Configuration / source |
|---|---|---|
| Extract claims and queries | `anthropic:claude-sonnet-5-5` (was Opus until 22.11, #88) | `PRAWDOWID_MODEL`, [verifier.py](../../prawdowid/verifier.py) |
| Rerank fragments | `anthropic:claude-haiku-5-5` | `PRAWDOWID_RERANK_MODEL`, [rerank.py](../../prawdowid/rerank.py) |
| Label evidence | `anthropic:claude-sonnet-5-5` | `PRAWDOWID_JUDGE_MODEL`, [judge.py](../../prawdowid/judge.py) |

These are literal code defaults, not a statement about currently available public model names.
Availability is UNCONFIRMED. The saved eval's JSON does not record its models; the results section
below says what it ran on. All model calls use PydanticAI native structured output through the
installed Anthropic provider. Another provider needs its PydanticAI extra (only
`pydantic-ai-slim[anthropic,mcp]` is installed, [pyproject.toml](../../pyproject.toml)), its key
and an image rebuild; none is demonstrated. The EU-processed option is described under "Deployment, storage and data processing" below. Compose forwards only `PRAWDOWID_MODEL`, so changing
the rerank or judge model on the server also needs a line in [compose.yaml](../../compose.yaml).
Web search (step 2b) is **Perplexity's Search API** (`perplexity_search` in `prawdowid/websearch.py`,
`perplexityai` SDK, restricted to the allowlist with `search_domain_filter`, country PL, language pl)
when `PERPLEXITY_API_KEY` is set. Without it, or with `PRAWDOWID_SEARCH_PROVIDER=tavily`, it is
**Tavily** (`tavily_search`, behind the per-query cache), which is also what the eval numbers in this
repo were measured with. Tavily replaced DuckDuckGo (#7, proposed as #20; wired as #45) because DuckDuckGo via `ddgs` returned no
results from our machines and left retrieval empty. Retrieval providers and their terms are listed
in [sources.md](sources.md).

## Deployment, storage and data processing

[Dockerfile](../../Dockerfile) builds the uv backend, runs it as `nobody` and starts uvicorn.
[Frontend Dockerfile](../../frontend/Dockerfile) serves static files with nginx.
[compose.yaml](../../compose.yaml) publishes only the frontend by default, with backend health
checks. The Discord service and local PostgreSQL service are opt-in profiles. Compose now
forwards the extraction model setting, Anthropic key, `GOOGLE_FACTCHECK_API_KEY`,
`PERPLEXITY_API_KEY`, `TAVILY_API_KEY`, `PRAWDOWID_SEARCH_PROVIDER`, `EUVSDISINFO_API_KEY`, `PRAWDOWID_GOVPL`, `PRAWDOWID_INCIDENTS_PATH` and the
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
and queries go to Google, Perplexity or Tavily and EUvsDisinfo when configured. Details and open gaps (Discord
has no delete command, Docker stdout logs sit outside retention): [docs/privacy.md](../privacy.md).
Who processes what, from each provider's own terms read on 22.11.2026. The full table, with
retention, training use and links to the terms, is in
[docs/privacy.md](../privacy.md#where-data-is-processed).

| Processor | Receives | Processes in |
|---|---|---|
| Anthropic (extraction, rerank, judge) | Masked text; masked claims and public fragments | Global by default (US, Europe, Asia, Australia), stored in the US. The first-party API has no EU-only setting |
| Perplexity (web search, when its key is set) | The same masked search queries as Tavily, plus the domain allowlist, country PL and language pl. Not cached | Perplexity AI, Inc. (USA); where the API processes data is not stated, UNCONFIRMED |
| Tavily (web search, the fallback) | Masked search queries: the model's queries, the claim sentence and one search of it restricted to fact-checker domains (#106) | United States. An EU endpoint exists for selected customers only |
| Google Fact Check Tools | Masked claim text and up to 8 short queries per claim, each masked (#100) | Not stated for this API, UNCONFIRMED. Google's privacy policy says its servers are worldwide |
| EUvsDisinfo MCP | Claim text, cut to 200 characters | Not stated, UNCONFIRMED |
| www.gov.pl search | Search queries, or the claim when the model wrote none | Not stated, UNCONFIRMED |
| Sites a pasted link points to | The URL as pasted, unmasked: a name or e-mail in its path or query string reaches the site | The site's own hosting |
| OVHcloud VPS | Everything the app stores | Limburg, Germany |
| Discord (bot; #59 says it is not deployed, not checked) | The typed command and our reply | United States |

Migration path: the three model steps are chosen by `PRAWDOWID_MODEL`, `PRAWDOWID_RERANK_MODEL`
and `PRAWDOWID_JUDGE_MODEL` (PydanticAI model strings). The same Claude models can run in the EU
through Amazon Bedrock EU inference profiles (for example `bedrock:eu.anthropic.claude-sonnet-5-5`).
That takes the variables, the `bedrock` dependency extra and the `environment:` list in
`compose.yaml`, and is expected to need no prompt or code change (Bedrock ignores the retry
setting the agents pass, so botocore's default retries apply). It has not been run. After it,
web search (Perplexity, or Tavily as the fallback) and the Discord channel still leave the EEA. Fact Check (Google), EUvsDisinfo
and www.gov.pl state no location, so they stay UNCONFIRMED. Steps and open points:
[docs/privacy.md](../privacy.md#migration-path-to-an-eu-processed-model).

Browser traffic and fetched evidence also pass through other parties' systems. See
[risks.md](risks.md) for code references and [sources.md](sources.md) for storage limits.

Moderator cases (scenario H, [cases.py](../../prawdowid/cases.py), #79): after the verdicts,
`POST /api/checks` files a check that needs a person. That means a claim that ended `brak
wystarczających dowodów`, a logged security event, or a claim on a high-risk topic (evacuation or
RCB alert, health emergency, elections, mobilisation; a short list in code) that ended false,
misleading or without enough evidence. A question joins an open case when its claim and one of the
case's claims share enough word stems (Jaccard of at least `PRAWDOWID_CASE_MIN_SIMILARITY`, 0.5,
over the corpus search's stems), and the case count goes up; otherwise it opens a new case. The
store is a JSONL file next to the check log, on the same volume, under a file lock. It holds masked
claims, keeps each question 30 days and drops a session's questions when the session is deleted.
The answer carries `moderator_case` only after the write, and the channels say "Zgłoszenie trafiło
do kolejki moderatora (sprawa N)" only then, so a failed write never reads as a hand-off (brief
section 5). The moderator or analyst who holds `PRAWDOWID_ADMIN_TOKEN` reads the queue at
`GET /api/cases`. Without that variable nobody could read it, so no check is filed and no answer
mentions a moderator. There is no push notification and no moderator screen beyond that JSON list.
It has not run on the live server yet; the server's `.env` needs the variable first
([deploy.md](../deploy.md)).

## Default limits, not performance measurements


| Limit | Default | Source |
|---|---|---|
| Input / checked page prefix | 5000 characters | [app.py](../../prawdowid/app.py), [verifier.py](../../prawdowid/verifier.py) |
| Fully considered claims / queries per checkable claim | 3 / 2 | [verifier.py](../../prawdowid/verifier.py) |
| Check budget / API timeout | 40 s / 60 s | [pipeline.py](../../prawdowid/pipeline.py), [app.py](../../prawdowid/app.py) |
| Extraction call timeout | 45 s provider setting, bounded by the shared check deadline | [verifier.py](../../prawdowid/verifier.py) |
| Web query / whole page fetch budget | 10 s / 8 s | [websearch.py](../../prawdowid/websearch.py) |
| Link fetch | 10 s, 3 redirects, `2 * 1024 * 1024` bytes | [link.py](../../prawdowid/link.py) |
| Evidence fragments: size / candidates / retained | 800 characters / 60 / 12 | [rerank.py](../../prawdowid/rerank.py) |
| Requests per client IP | 10/minute; the bot shares its IP across users | [app.py](../../prawdowid/app.py), [Discord client](../../prawdowid/discord_bot.py) |
| Discord response cap | 5 messages of 2000 characters, with truncation notice | [discord_bot.py](../../prawdowid/discord_bot.py) |

Extraction and URL fetching share the check deadline. A cut extraction returns a technical notice;
unfinished claims return `not_checked`. A judge outage also maps to `not_checked`.
Request deadlines
do not establish server capacity; [cost.md](cost.md) describes the unmeasured load behaviour.
There is no OCR or reverse image search. The moderator queue (#79, above) files cases only while
`PRAWDOWID_ADMIN_TOKEN` is set. The evidence corpus is built and
searched in every check ([corpus.md](../corpus.md)); a live Discord run remains open in
[WORKLOG](../../WORKLOG.md). Two URL cases (U01, U02) are in the saved full run; do not present
their latency as a URL benchmark.

## Saved test results and reproduction

Latest tracked result: [evals/results/latest.json](../../evals/results/latest.json), the same file as
[history/20261122T061635.151613Z-a14b93c-full.json](../../evals/results/history/20261122T061635.151613Z-a14b93c-full.json):
timestamp `2026-11-22T06:26:43+00:00`, commit `a14b93c29a93ab9866ca5de6e86bcd82fd1b691f`,
`dirty: false`, `mode: "full"`, `n_cases: 75`, `concurrency: 4`, `coverage_ok: true`,
`overall_pass: false`, run with `--corpus`. Scenarios: `A, B, C, D, E, G, H, I, J, U`; E05-E15
skipped in this run (see the next table). The commit is the harness's: the JSON records only the
harness checkout, not the server code. The run used a local API on a laptop, not VPS staging, with
Tavily web search. The cases are our own set, not the jury's, and the values and targets below are
copied exactly from the file; the last column says what each value rests on:

| Metric | value | target | pass | rests on |
|---|---|---|---|---|
| macro_f1 | 0.9184736903785303 | >= 0.75 | true | the 69 cases with an expected verdict, five classes; 42 of them are labelled from a Demagog ClaimReview rating, which the product can adopt when Fact Check returns the rating of the same claim (#100), so on those cases the score also measures finding that rating |
| citation_coverage | 1.0 | >= 0.95 | true | claims with a factual verdict only |
| citation_correctness | 1.0 | >= 0.85 | true | quotes that cite a corpus document, checked for verbatim presence in it, not for support of the claim |
| abstention | 1.0 | >= 0.8 | true | 12 cases expecting `brak wystarczających dowodów` |
| injection_resistance | 1.0 | >= 0.9 | true | 7 pasted-text cases (E01-E04, FC-E01-FC-E03), each a canary in the pasted text; the patterns in `prawdowid/verifier.py` match FC-E01-FC-E03 phrase for phrase, so read those three as tuned on |
| median_latency_s | 20.462797979009338 | <= 30.0 | true | the first run of the cases, 4 in flight; 1 answer from the result cache is left out |
| end_to_end | 0.9866666666666667 | >= 1.0 | false | 74 of 75; only J01, a simulated Fact Check outage, came back `ok` with a verdict where `technical_error` is expected (A15 now passes) |
| channel_consistency | 1.0 | >= 1.0 | true | 6 G cases; first answer a direct `POST /api/checks` with `X-Channel: web`, second the bot's API client, not Discord; the second answers came from the shared result cache (#59), so this shows the cache returning the stored result |
| moderator_loop | 1.0 | >= 1.0 | true | 2 cases (H01, H02) |
| injection_verdict_correct | 1.0 | reported | true | the 7 injection cases |
| cost_per_100_usd | 3.446553 | reported | true | model tokens only, mean over 70 priced answers; 1 cache hit and the 4 simulated outages are left out |

Injection in a fetched page (E05-E15) ran separately on `main` 5e5be00, local API, Tavily, fixture
pages served from `https://faktczyfejk.pl/eval-fixtures`: 11 of 11 correct, injection_resistance
1.0, end_to_end 1.0. Files:
[20261122T075024.922599Z-5e5be00-full.json](../../evals/results/history/20261122T075024.922599Z-5e5be00-full.json)
and [20261122T075409.798208Z-5e5be00-full.json](../../evals/results/history/20261122T075409.798208Z-5e5be00-full.json)
(E08 and E14 rerun without the result cache); method in [eval-notes.md](../eval-notes.md). Combined
and labelled as two runs: 80 labelled cases, 73 correct, macro-F1 0.924. These two runs differ in
commit and time; do not quote the combined figures as one run.

Earlier runs, history only: the full run on ca48b84 had macro_f1 0.8027, median latency 17.84 s,
end_to_end 0.9733 (J01 and A15 failed), abstention 0.9167, moderator_loop 0.0, cost 4.2727 per 100,
E05-E15 skipped. The quick run on `edd34a5` had macro_f1 0.278 on 10 cases.

By scenario (correct of cases): A 21/23, B 7/10, C 6/6, D 8/8, E 7/7, G 5/6, H 2/2, I 6/7, J 3/4,
U 2/2; by case set: FC-* 28/32, A-J 39/43. Of the 8 misses, four expect `fałszywe` and got
`brak wystarczających dowodów` (B04, FC-A08, FC-I03) or `nie sprawdzono` (A10). Citation coverage counts evidence URL/quote
presence for factual verdicts, not evidence correctness; no manual citation spot-check is committed.
Verdict accuracy scores the main claim alone; citation metrics examine all returned claims. The JSON
does not record per-provider retrieval outcomes or model overrides. Runs before these are in
[HISTORY.md](../../evals/results/HISTORY.md), with [eval-notes.md](../eval-notes.md) on why some of
them are distorted.
Exact reproduction is UNCONFIRMED. Sources: [metrics](../../evals/metrics.py),
[runner](../../evals/run.py), [adapter](../../evals/adapter.py), [WORKLOG](../../WORKLOG.md).

Start the API with `make dev` and configured keys in ignored `.env`. In another terminal:

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick
```

This selects a quick subset of [evals/cases.jsonl](../../evals/cases.jsonl) and overwrites `latest.json`; calls may incur
provider charges. A missing key exercises failure paths, not the saved live conditions. For the
full run, as saved, remove `--quick` and add `--corpus corpus/evidence.jsonl` (needed for citation
correctness). The saved run also set `PRAWDOWID_EXTRA_CHANNELS=discord`, which exercises the bot's
API adapter but not Discord transport, and the same `PRAWDOWID_EVAL_TOKEN` on the server and the
runner, which the J cases need; E05-E15 need `PRAWDOWID_FIXTURE_BASE=https://faktczyfejk.pl/eval-fixtures`. Exact live reproduction is
UNCONFIRMED because external results and model versions can change.
