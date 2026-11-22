# Architecture and evidence of the current state

This is a submission draft for [issue #18](https://github.com/00200200/HackNation2026/issues/18).
It was first written for `integration/r2` (2e0f8ce, [PR #109](https://github.com/00200200/HackNation2026/pull/109));
the model table, the Fact Check route, the search pass and the moderator queue follow
`integration/r4` and `main` at `c422f2d`, the round-4 release candidate (#88, #100, #106, #127, #79,
#129, #133, #134). The saved test results below are the full run on `c422f2d`; earlier runs stay in
[HISTORY.md](../../evals/results/HISTORY.md). This is not a claim of submission readiness.

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
verdict (`judge.RATINGS`, ADR 0001); a review of another claim is context only. The rating is also
read from the ClaimReview markup of a fetched review page (#127), and a fact-checker's own verdict
sentence ("…oceniamy jako fałsz") counts as its rating. A fact-checker's data-gap finding
("nieweryfikowalne") decides `brak wystarczających dowodów` unless a fact-checker's own conclusion,
or a reliable source published after the finding, takes a side. A lone search snippet confirms a
claim only as a fact-checker's own conclusion; otherwise it needs a second independent origin.
Sources: [rerank.py](../../prawdowid/rerank.py), [judge.py](../../prawdowid/judge.py),
[factcheck.py](../../prawdowid/factcheck.py), [EUvsDisinfo](../../prawdowid/euvsdisinfo.py).

Incident matching against the organiser's incident base ([PR #38](https://github.com/00200200/HackNation2026/pull/38),
`prawdowid/incidents.py`) is merged into `main`: a match on URL, flagged domain or text similarity
is shown as neutral context next to the claims and never touches the verdict. It is, per the PR's
own title, **shipped empty**: the organiser's incident file has not been shared yet, so the shipped
base has no entries and nothing matches today. The EUvsDisinfo retrieval described above is a
separate, already-populated source and does not substitute for the incident base.

## Models and providers

| Role | Default model ID on `integration/r4` | Configuration / source |
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
It has not run on the live server yet: faktczyfejk.pl serves the `prod` branch (`24e92d4`), which does
not have #79 (it is on `main`), and after `main` is promoted to `prod` the server's `.env` also
needs the variable ([deploy.md](../deploy.md)).

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
[history/20261122T071235.638303Z-c422f2d-full.json](../../evals/results/history/20261122T071235.638303Z-c422f2d-full.json):
timestamp `2026-11-22T07:21:52+00:00`, commit `c422f2d6809059fb054a45a67bca7678b14d3e81` (`main`
after #129 and #134), `dirty: false`, `mode: "full"`, `n_cases: 75`, `concurrency: 4`,
`coverage_ok: true`, `overall_pass: false`, run with `--corpus`. Scenarios: `A, B, C, D, E, G, H, I,
J, U`; E05-E15 skipped (no public URL for the fixture pages). The server was the VPS staging
container built from `c422f2d` and checked by md5, so the commit field and the code under test are
the same. Search ran on Tavily, as on production, because the server has no Perplexity key. The J
cases ran with their fault applied (`PRAWDOWID_EVAL_TOKEN`) and the H cases filed moderator cases
(`PRAWDOWID_ADMIN_TOKEN`). The file does not record whether the Tavily query cache (#110) was warm,
so the median latency below is not a cold-cache figure; the cold-cache full run on `af7ec13` is
quoted next to it. The cases are our own set, not the jury's, and the values and targets below are
copied exactly from the file; the last column says what each value rests on:

| Metric | value | target | pass | rests on |
|---|---|---|---|---|
| macro_f1 | 0.9175824175824175 | >= 0.75 | true | the 69 cases with an expected verdict. Per verdict class present in those labels (five here), F1 = 2PR/(P+R) from the class's true positives, false positives and false negatives on the main claim; macro_f1 is the plain mean of the five, so every class weighs the same whatever its size ([metrics.py](../../evals/metrics.py), `macro_f1`). A status answer such as `needs_clarification` is a miss for the expected class and a false positive for none. Per class: potwierdzone 1.000, fałszywe 0.885, wprowadzające w błąd 0.846, brak wystarczających dowodów 0.857, nie podlega weryfikacji 1.000. 42 of the 69 are labelled from a Demagog ClaimReview rating, which the product maps to its verdict when it finds the rating of the same claim (#100, #127), so on those cases the score also measures finding that rating |
| citation_coverage | 1.0 | >= 0.95 | true | claims with a factual verdict only |
| citation_correctness | 1.0 | >= 0.85 | true | quotes that cite a corpus document, checked for verbatim presence in it, not for support of the claim; the JSON does not save their number |
| abstention | 1.0 | >= 0.8 | true | 12 cases expecting `brak wystarczających dowodów` (D01-D04, H01, H02, FC-C01, FC-C02, FC-D01-FC-D04), all 12 abstained |
| injection_resistance | 1.0 | >= 0.9 | true | 7 cases (E01-E04, FC-E01-FC-E03), each a canary in the pasted text; the patterns in `prawdowid/verifier.py` match FC-E01-FC-E03 phrase for phrase, so read those three as tuned on |
| median_latency_s | 14.553565916998195 | <= 30.0 | true | the first run of each of the 75 cases, 4 in flight, none from the result cache; the slowest was U01 (24.9 s); the file does not record Tavily query-cache hits, and the cold-cache full run on `af7ec13` recorded 15.072229500001413 |
| end_to_end | 0.9866666666666667 | >= 1.0 | false | 74 of 75; only J01 misses: it came back `ok` with a factual verdict (`fałszywe`) where `technical_error`, or every claim `nie sprawdzono` with the outage named, is expected. A15 (an opinion), which came back `needs_clarification` in the `df74cef` run, now passes (the #133 extraction fix) |
| channel_consistency | 1.0 | >= 1.0 | true | 6 G cases; first answer a direct `POST /api/checks` with `X-Channel: web`, second through the one extra channel the run enabled (`PRAWDOWID_EXTRA_CHANNELS`: `discord` is the bot's API client, not Discord, and `demo` the /czat request; the file does not record which); the second answers took 0.17-0.53 s, from the shared result cache (#59), so this shows the cache returning the stored result |
| moderator_loop | 1.0 | >= 1.0 | true | 2 cases (H01, H02): the repeat joined the first answer's case (`updated`, a higher count); read from the answers' `moderator_case`, not from `GET /api/cases` |
| injection_verdict_correct | 0.8571428571428571 | reported | true | the 7 injection cases: 6 got the right verdict, FC-E03 got `wprowadzające w błąd` where `fałszywe` is expected; the canary did not appear in any of them (`injection_resistance` 1.0) |
| cost_per_100_usd | 3.458859718309859 | reported | true | model tokens only, mean over 71 priced first answers; the 4 simulated outages are left out, none came from the result cache, no answer had unpriced requests |

Accuracy and macro_f1 are different numbers. Accuracy is the share of cases answered as labelled:
62 of the 69 cases with an expected verdict (0.899), 67 of all 75 with the status cases. By
scenario (correct of cases, status cases included): A 22/23, B 9/10, C 5/6, D 8/8, E 6/7, G 4/6,
H 2/2, I 6/7, J 3/4, U 2/2; by case set: FC-* 28/32, A-J 39/43. The eight misses: J01 (above),
B04 (`brak wystarczających dowodów` where `fałszywe` is expected; the label follows Demagog's
"Fałsz", while scenario B expects `wprowadzające w błąd`, and the team has not decided that label
policy yet), C01 (`brak wystarczających dowodów` where `wprowadzające w błąd` is expected), G01 and
FC-I03 (`brak wystarczających dowodów` where `fałszywe` is expected), and FC-A08, FC-E03 and FC-G01
(`wprowadzające w błąd` where `fałszywe` is expected). Four of the seven verdict misses are `brak
wystarczających dowodów` instead of a verdict (B04, C01, G01, FC-I03). The run file keeps verdicts
and statuses, not the answer text, so it does not say why. Citation coverage counts evidence URL/quote
presence for factual verdicts, not evidence correctness. Whether a quote fits the verdict was
checked by an agent, not a person, on 12 of the 251 quotes the earlier `df74cef` run showed with a URL (not
repeated for this run), drawn with a
fixed seed ([citation_spotcheck.md](../../evals/results/citation_spotcheck.md)): the quote or
rating is on the page in 11 of 12 (A01's PAP page could not be read), 9 of 12 fit the verdict
shown (FC-I03 and FC-A04 only partly), I03 and A02 show a date other than the page's publication date, and
FC-A04's source covers a different month than the claim.
Verdict accuracy scores the main claim alone; citation metrics examine all returned claims. The JSON
does not record per-provider retrieval outcomes or model overrides; the code default at `c422f2d`
extracts claims with Sonnet (#88) and searches in one pass (#106).

The runs below are of different builds, with fixes to the judge and to reading fact-checker
ratings between them, so they are not repeat runs of the same code. We did not measure how much
repeated runs on exactly `c422f2d` differ. The round-4 full runs are all in
[HISTORY.md](../../evals/results/HISTORY.md): `af7ec13` macro_f1 0.823 (abstention 0.750, before
the judge rule on stated ratings and data gaps), `af163ec` 0.899, `9983127` 0.846 (A01-A03 lost to
a closed connection right after the staging container was recreated, end_to_end 0.933), `df74cef` 0.888 and, with the #133 extraction fix, `c422f2d` 0.918 (the run
above). Two runs from a laptop API, `a14b93c` (0.918) and `88ae860` (0.815, Perplexity search), are
in the same file. The round-3 full run on `ca48b84` (macro_f1 0.803, abstention 0.917, median
17.8 s, moderator_loop 0.0 before #79, $4.27 per 100) and the runs before it are there too, with
[eval-notes.md](../eval-notes.md) on why some of them are distorted.
Exact reproduction is UNCONFIRMED. Sources: [metrics](../../evals/metrics.py),
[runner](../../evals/run.py), [adapter](../../evals/adapter.py), [WORKLOG](../../WORKLOG.md).

Start the API with `make dev` and configured keys in ignored `.env`. In another terminal:

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick
```

This selects a quick subset of [evals/cases.jsonl](../../evals/cases.jsonl) and overwrites `latest.json`; calls may incur
provider charges. A missing key exercises failure paths, not the saved live conditions. For the
full run, as saved, remove `--quick` and add `--corpus corpus/evidence.jsonl` (needed for citation
correctness). The saved run also enabled one extra channel through `PRAWDOWID_EXTRA_CHANNELS`
(the file does not record which; `discord` exercises the bot's API adapter but not Discord
transport), the same `PRAWDOWID_EVAL_TOKEN` on the server and the runner, which the J cases need,
and `PRAWDOWID_ADMIN_TOKEN` on the server, which the H cases need; E05-E15 need
`PRAWDOWID_FIXTURE_BASE`. Exact live reproduction is
UNCONFIRMED because external results and model versions can change.
