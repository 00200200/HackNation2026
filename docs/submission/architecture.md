# Architecture and evidence of the current state

This is a submission draft for [issue #18](https://github.com/00200200/HackNation2026/issues/18).
The implementation inspected was originally the `LukiLenkiewicz/issue11-fanout` stack at `cacfb4e`;
that stack (per-claim fan-out, judge, local source store, link input) is now merged into `main`
(PRs #37, #30, #42, #28/#44). The implementation described below is `main`'s (`1aa173f`, 22.11.2026), after that merge, except where a row names PR #126 (branch `integration/r3`, head `ca48b84`, open; it contains PR #109 and supersedes it). Those are changes awaiting merge, listed in the README section "Zmiany czekające na scalenie". A later commit to PR #126 needs a recheck of the rows that name it.
The measured commits, as the run files record them, are identified below: `95e6177` (the run on `main`) predates that merge, and the cited full run on `ca48b84` (the head of PR #126) is not on `main` either (its file is in PR #128 and PR #123). This is not a claim of
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
         + evidence corpus (BM25 over corpus/evidence.jsonl; PR #126, `main` does not search it)
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
| Extract claims and queries | `anthropic:claude-opus-5-5` (`anthropic:claude-sonnet-5-5` from #88 in PR #126) | `PRAWDOWID_MODEL`, [verifier.py](../../prawdowid/verifier.py) |
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
| Google Fact Check Tools | Masked claim text; in PR #126 up to 8 short queries per claim, each masked (#100) | Not stated for this API, UNCONFIRMED. Google's privacy policy says its servers are worldwide |
| EUvsDisinfo MCP | Claim text, cut to 200 characters | Not stated, UNCONFIRMED |
| www.gov.pl search | Search queries, or the claim when the model wrote none | Not stated, UNCONFIRMED |
| Sites a pasted link points to | The URL as pasted, unmasked: a name or e-mail in its path or query string reaches the site | The site's own hosting |
| OVHcloud VPS | Everything the app stores | Limburg, Germany |
| Discord (bot; #59 says it is not deployed, not checked) | The typed command and our reply | United States |

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

Values are those of PR #126 (`ca48b84`), unless a cell names `main`.

| Limit | Default | Source |
|---|---|---|
| Input / checked page prefix | 5000 characters | [app.py](../../prawdowid/app.py), [verifier.py](../../prawdowid/verifier.py) |
| Fully considered claims / queries per checkable claim | 3 / 3 (`main`: 5 / 3) | [verifier.py](../../prawdowid/verifier.py) |
| Check budget / API timeout | 40 s / 60 s (`main`: 25 s / 60 s) | [pipeline.py](../../prawdowid/pipeline.py), [app.py](../../prawdowid/app.py) |
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
There is no moderator queue, OCR or reverse image search. The live Discord run remains open in
[WORKLOG](../../WORKLOG.md). The case set on `main` ([cases](../../evals/cases.jsonl)) has no URL input.
PR #126 has 13 of 86 cases with a URL input (`U01`, `U02`, `E05` to `E15`) and the full run on `ca48b84` covers only `U01` and `U02`
(`E05` to `E15` were skipped), so their 28.5 s and 27.8 s are two data points, not a URL benchmark.

## Saved test results and reproduction

`evals/results/latest.json` is not a stable pointer: it holds one run on `main`, another in PR #109 and PR #126, and a third in PR #128.
The runs below are therefore identified by the commit each file records and linked by permalink to the file at a fixed commit.

The cited run is the full run on `ca48b84`, the head of [PR #126](https://github.com/00200200/HackNation2026/pull/126):
[run file](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json), `2026-11-22T02:27:29+00:00`, recorded commit
`ca48b84390d0df22881024155a37bfafba606ce2`, `mode: "full"`, `n_cases: 75`, `dirty: false`, `coverage_ok: true`, `overall_pass: false`, `concurrency: 4`.
The file is in [PR #128](https://github.com/00200200/HackNation2026/pull/128) (`6126ac9`, where it is also `latest.json`) and in
[PR #123](https://github.com/00200200/HackNation2026/pull/123) (`cd61db5`), not on `main` and not in PR #126.
75 of the 86 cases of `evals/cases.jsonl` in PR #126 ran: `E05` to `E15` were skipped (no public URL for the fixture pages,
[#94](https://github.com/00200200/HackNation2026/issues/94)), and no case had a harness error. The file records neither the
extraction model, nor the machine, nor the flags of the run, so exact reproduction is UNCONFIRMED. The `commit` and `dirty` fields describe the checkout the harness ran from (`evals/run.py`), and the harness calls the server at `PRAWDOWID_URL` (`evals/adapter.py`), so whether that server was built from `ca48b84`, and whether it was clean, is UNCONFIRMED as well. A later commit in PR #126 needs a new run
([#16](https://github.com/00200200/HackNation2026/issues/16)).

Other saved runs, not cited as the measurement of the current build:

- Quick run on `edd34a5`, `2026-11-22T00:37:27+00:00`, 10 cases, one per scenario ([file](https://github.com/00200200/HackNation2026/blob/ca48b84390d0df22881024155a37bfafba606ce2/evals/results/latest.json), which is `latest.json` in PR #109 and
  PR #126): macro-F1 0.278, end-to-end 0.9, median 24.9 s, USD 4.91 per 100 (rounded from the file).
  Extraction ran on Opus (per the message of `83d6c65`, not recorded in the JSON).
- Quick run on `ca48b84`, `2026-11-22T02:15:53+00:00`, 10 cases, one per scenario ([file](https://github.com/00200200/HackNation2026/blob/cd61db592e81aa7b22a24690cb090d64116d17dd/evals/results/history/20261122T021403.618691Z-ca48b84-quick.json), in PR #123 only): macro-F1
  0.75, median 29.8 s, USD 5.54 per 100 (rounded from the file). The full run on the same commit replaces it.
- Quick run on `95e6177`, `2026-11-21T19:10:57+00:00`, 9 cases ([file](https://github.com/00200200/HackNation2026/blob/1aa173f6e651f7ff2bdacebb2d4384658efc2d48/evals/results/latest.json), which is `latest.json` on `main`). It predates the
  judge, the retrieval pipeline and the check log. At that commit (`prawdowid/` is identical in `e9a7f86` on `main`)
  `verifier.to_check_result` returned a constant `insufficient_evidence` for every checkable claim, and `judge.py`, `pipeline.py` and
  `checklog.py` did not exist. Its values describe that stub, not the pipeline: do not quote them
  ([eval-notes.md](../eval-notes.md)).

The following values and targets are copied exactly from the full-run file:

| Metric | value | target | pass |
|---|---|---|---|
| macro_f1 | 0.8026992266992267 | >= 0.75 | true |
| citation_coverage | 1.0 | >= 0.95 | true |
| citation_correctness | 1.0 | >= 0.85 | true |
| abstention | 0.9166666666666666 | >= 0.8 | true |
| injection_resistance | 1.0 | >= 0.9 | true |
| median_latency_s | 17.842587917002675 | <= 30.0 | true |
| end_to_end | 0.9733333333333334 | >= 1.0 | false |
| channel_consistency | 1.0 | >= 1.0 | true |
| moderator_loop | 0.0 | >= 1.0 | false |
| injection_verdict_correct | 1.0 | reported | true |
| cost_per_100_usd | 4.272704084507042 | reported | true |

Bases of the ratios, counted from the same file. `macro_f1` is 55 correct of 69 cases that expect a verdict; the six cases that
expect a status (J01, J02, FC-J01, FC-J02, U01, U02) are not in it. Counting all 75 cases, 25 of the 32 `FC-` cases and 35 of the other 43
are correct.
`citation_coverage` runs over every factual-verdict claim of the `ok` answers, a number the file does not record (it keeps only each
case's first-claim verdict, and 52 `ok` answers have a factual one, so at least 52 claims). `citation_correctness` is not
null, so the run had a corpus; it checks only that a quote occurs in the cited corpus document, for quotes from documents the corpus
holds, and the file records no quote count. `abstention` is 11 of 12 cases that expect `brak wystarczających dowodów` (the
miss is `FC-D02`). `injection_resistance` rests on 7 cases (`E01` to `E04`, `FC-E01` to `FC-E03`, all injections in the input text);
no page injection was scored, so it says nothing about the 11 skipped page cases. `end_to_end` is 73 of 75: `A15` (a question of
opinion that expects `nie podlega weryfikacji`) returned status `needs_clarification`, and `J01` (a simulated Fact Check outage whose
answer must not end in a factual verdict) returned status `ok` with `potwierdzone` for its first claim. `channel_consistency` rests on
6 cases (`G01`, `G02`, `FC-G01` to `FC-G04`) whose second answers took 0.09 to 0.21 s and most likely came from the result
cache; it compares the answers, not their correctness (`G01` and `FC-G04` have a wrong verdict). `moderator_loop` is 0.0 on the two
repeat cases (`H01`, `H02`): the loop is not built on `main` or in PR #126.

`median_latency_s` is the median of the first answers of all 75 cases, with no cache hit among them: 8 of them took more than
30 s, the slowest, `D03`, 38.6 s, and the two URL cases, `U01` (a long gov.pl page from #63) and `U02`, 28.5 s and 27.8 s.
`cost_per_100_usd` is the mean `cost_usd` of 71 priced answers times 100; the four cases that set a simulated fault are left out,
no answer had an unpriced request (`lower_bound: false`), and it covers model calls only (extraction, rerank, judge), not search, hosting
or the channel. [cost.md](cost.md) turns it into USD 42.73 per 1,000 checks.

`null` means not measured, not passed. Citation coverage counts evidence URL/quote presence for
factual verdicts, not evidence correctness. Citation correctness only tests text occurrence, not semantic support, and no manual
citation spot-check is committed: `evals/metrics.py` points to `evals/results/citation_spotcheck.md`, a file that does not exist in
`main`, PR #126, PR #123 or PR #128.
Verdict accuracy scores the main claim alone; citation metrics examine all returned claims.
The JSON does not record per-provider retrieval outcomes or model overrides; those conditions are
UNCONFIRMED for exact reproduction. Sources: [metrics](../../evals/metrics.py),
[runner](../../evals/run.py), [adapter](../../evals/adapter.py), [WORKLOG](../../WORKLOG.md).

Start the API with `make dev` and configured keys in ignored `.env`. In another terminal:

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick
```

This selects a quick subset of [evals/cases.jsonl](../../evals/cases.jsonl) and overwrites `latest.json`; calls may incur
provider charges. A missing key exercises failure paths, not the saved live conditions. For a
full run, drop `--quick` and add `--corpus corpus/evidence.jsonl` (the usage line of `evals/run.py`); without `--corpus`
`citation_correctness` is null.
To exercise the bot's API adapter, add
`PRAWDOWID_EXTRA_CHANNELS=discord`; this does not test Discord transport itself. Exact live
reproduction is UNCONFIRMED because external results and model versions can change.
