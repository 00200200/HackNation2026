# Architecture and evidence of the current state

This is a submission draft for [issue #18](https://github.com/00200200/HackNation2026/issues/18).
The implementation inspected was originally the `LukiLenkiewicz/issue11-fanout` stack at `cacfb4e`;
that stack (per-claim fan-out, judge, local source store, link input) is now merged into `main`
(PRs #37, #30, #42, #28/#44). The implementation described below is `main`'s, after that merge.
The measured product commit is identified below and predates this merge; this is not a claim of
submission readiness.

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
Availability and the model overrides used in the saved eval are UNCONFIRMED: its JSON does not
record them. All model calls use PydanticAI native structured output through the installed
Anthropic provider. Alternative provider dependencies and credentials are not demonstrated; the
EU-processed option is described under "Deployment, storage and data processing" below.
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
`TAVILY_API_KEY`, `EUVSDISINFO_API_KEY` and `PRAWDOWID_INCIDENTS_PATH`, and already points the
check log and source cache at a writable `/tmp` path for the non-root `nobody` user.

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
Personal data (e-mail, IBAN/NRB, card number, PESEL, phone; regex and checksums, not names or
addresses) is masked by `privacy.mask_personal_data` before the text reaches the extraction model
and again in every log line, web search and own-store query (#17, #39, merged into `main`).
Each check is kept 30 days as one masked record in the check log (`prawdowid/checklog.py`), which
the user can delete per session (`DELETE /api/sessions/{id}`, a web button). Input goes to
Anthropic masked (a placeholder keeps the sentence shape so claims still split); masked claim text
and queries go to Google, Tavily and EUvsDisinfo when configured. Details and open gaps (Discord
has no delete command, Docker stdout logs sit outside retention): [docs/privacy.md](../privacy.md).
Who processes what, from each provider's own terms read on 22.11.2026. The full table, with
retention, training use and links to the terms, is in
[docs/privacy.md](../privacy.md#where-data-is-processed).

| Processor | Receives | Processes in |
|---|---|---|
| Anthropic (extraction, rerank, judge) | Masked text; masked claims and public fragments | Global by default (US, Europe, Asia, Australia), stored in the US. The first-party API has no EU-only setting |
| Tavily (web search) | Masked search queries, or the masked claim when the model wrote none or the first search found too little | United States. An EU endpoint exists for selected customers only |
| Google Fact Check Tools | Masked claim text | Not stated for this API, UNCONFIRMED. Google's privacy policy says its servers are worldwide |
| EUvsDisinfo MCP | Claim text, cut to 200 characters | Not stated, UNCONFIRMED |
| www.gov.pl search | Search queries, or the claim when the model wrote none | Not stated, UNCONFIRMED |
| Sites a pasted link points to | The URL as pasted, unmasked: a name or e-mail in its path or query string reaches the site | The site's own hosting |
| OVHcloud VPS | Everything the app stores | Limburg, Germany |
| Discord (bot, not deployed yet) | The typed command and our reply | United States |

Migration path: the three model steps are chosen by `PRAWDOWID_MODEL`, `PRAWDOWID_RERANK_MODEL`
and `PRAWDOWID_JUDGE_MODEL` (PydanticAI model strings). The same Claude models can run in the EU
through Amazon Bedrock EU inference profiles (for example `bedrock:eu.anthropic.claude-opus-5-5`).
That takes the variables, the `bedrock` dependency extra and the `environment:` list in
`compose.yaml`, and is expected to need no prompt or code change (Bedrock ignores the retry
setting the agents pass, so botocore's default retries apply). It has not been run. After it,
web search (Tavily) and the Discord channel still leave the EEA. Fact Check (Google), EUvsDisinfo
and www.gov.pl state no location, so they stay UNCONFIRMED. Steps and open points:
[docs/privacy.md](../privacy.md#migration-path-to-an-eu-processed-model).

Browser traffic and fetched evidence also pass through other parties' systems. See
[risks.md](risks.md) for code references and [sources.md](sources.md) for storage limits.

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
There is no moderator queue, OCR or reverse image search. The demo corpus and live Discord run
remain open in [WORKLOG](../../WORKLOG.md). URL inputs are not exercised by the saved eval set
([cases](../../evals/cases.jsonl)); do not present its latency as a URL benchmark.

## Saved test results and reproduction

Two tracked runs exist, and which one [evals/results/latest.json](../../evals/results/latest.json)
holds depends on whether [PR #109](https://github.com/00200200/HackNation2026/pull/109) is merged.

- On `main` it is the quick run of `2026-11-21T19:10:57+00:00` at product commit `95e6177`, 9 cases.
  It predates the judge, the retrieval pipeline and the check log. At that commit (`prawdowid/` is
  identical in `e9a7f86` on `main`) `verifier.to_check_result` returned a constant
  `insufficient_evidence` for every checkable claim, and `judge.py`, `pipeline.py` and `checklog.py`
  did not exist. Its values describe that stub, not the pipeline: do not quote them
  ([eval-notes.md](../eval-notes.md)).
- In PR #109 it is the quick run of `2026-11-22T00:37:27+00:00` at product commit
  `edd34a5d2dd7f15515e27f51fa06bc2f1c4b3acb`, `dirty: false`, `mode: "quick"`, `n_cases: 10`,
  `coverage_ok: true`, `overall_pass: false`. Scenarios: `A, B, C, D, E, G, H, I, J, U`, one case
  each; `E05` and `E06` skipped (no public URL for the fixture page). It ran on the VPS staging with
  extraction on Opus (per the message of `83d6c65`, not recorded in the JSON). This is a quick regression run, not
  the full jury-sized evaluation, even though the saved `coverage_ok` flag is true. A full run is
  pending ([#16](https://github.com/00200200/HackNation2026/issues/16)).

The following values and targets are copied exactly from the second file:

| Metric | value | target | pass |
|---|---|---|---|
| macro_f1 | 0.2777777777777778 | >= 0.75 | false |
| citation_coverage | 1.0 | >= 0.95 | true |
| citation_correctness | null | >= 0.85 | null |
| abstention | 1.0 | >= 0.8 | true |
| injection_resistance | 1.0 | >= 0.9 | true |
| median_latency_s | 24.877917104000517 | <= 30.0 | true |
| end_to_end | 0.9 | >= 1.0 | false |
| channel_consistency | 1.0 | >= 1.0 | true |
| moderator_loop | 0.0 | >= 1.0 | false |
| injection_verdict_correct | 1.0 | reported | true |
| cost_per_100_usd | 4.912332 | reported | true |

Each ratio rests on a handful of cases: `citation_coverage` on one claim (`E01`), `abstention` on two
(`D01`, `H01`), `injection_resistance` on one (`E01`, an injection in the input text; no page
injection was scored), `channel_consistency` on one (`G01`, whose second answer took 0.22 s and most
likely came from the result cache). The slowest case, `U01`, took 37.4 s, above the 30 s target. The
cost covers model calls only (extraction on Opus, rerank, judge), not search, hosting or the channel.
On the same ten cases with only `PRAWDOWID_MODEL` changed to Sonnet, the commit message of `83d6c65`
reports macro-F1 0.375, median 18.3 s and about USD 3.96 per 100 checks; that run's file was not
saved, so it is UNCONFIRMED.

`null` means not measured, not passed. Citation coverage counts evidence URL/quote presence for
factual verdicts, not evidence correctness. Citation correctness needs a corpus and would only
test text occurrence, not semantic support; no manual citation spot-check is committed.
Verdict accuracy scores the main claim alone; citation metrics examine all returned claims.
The JSON does not record per-provider retrieval outcomes or model overrides; those conditions are
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
