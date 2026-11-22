# Reference

Configuration, API and repository layout. The overview and how to run it are in the [README](../README.md).

## How a check runs

The verifier sends the text to Claude (through PydanticAI) and gets back a list of
claims, each marked checkable or not. The model never decides whether a claim is true. Each
checkable claim then goes through `prawdowid/pipeline.py` in parallel with the others: Google Fact
Check, EUvsDisinfo known narratives (context only, never a verdict on its own), the www.gov.pl site
search (ministry and RCB pages; web search leaves www.gov.pl to it) and web search on
allowlisted domains (our own database, #19, is out of the pipeline for now), then
rerank and a judge that labels quotes; the verdict is set in code (`judge.decide`). The whole check
has one time budget (`PRAWDOWID_CHECK_BUDGET_S`, 40 s). A claim that runs out of time, or whose
sources failed (all of them, or one that could decide the verdict while the rest is not enough),
comes back `not_checked` with the reason, never as a verdict. An
opinion, forecast or question is `not_verifiable`. A link is fetched (`prawdowid/link.py`) and the page's
main text is checked like pasted text; a blocked page, paywall, login wall, social media post,
private address or file that is not HTML or PDF comes back as `cannot_check` with a request to
paste the text. Personal data (PESEL, ID card, passport, phone, e-mail, account and card numbers) is masked before
the text goes to the model. Each check is logged to stdout (session, status, latency, input length)
with a second line for the model call (model, input and output tokens, latency), and kept for 30
days as one masked record in the check log, which the user can delete per session. When
`PRAWDOWID_ADMIN_TOKEN` is set, a claim without enough evidence, a security event, or an
unconfirmed claim on a high-risk topic also goes to the moderator queue (`prawdowid/cases.py`,
scenario H): a similar question joins the same case, and the answer says "Zgłoszenie trafiło do
kolejki moderatora (sprawa N)" only after the case was written. The moderator reads the queue
through `GET /api/cases` (see API). Without the token nobody could read it, so nothing is filed and
no answer mentions a moderator. A link check
also logs the final URL with secret query values removed and personal data masked, the page's
SHA-256, and the text and verdict of every claim. The page text itself is never logged. Successful
web evidence fetches are cached in `corpus/docs.jsonl` as metadata only (full text only once a
domain's licence is confirmed, none today), one record per URL, dropped after 30 days. Details:
[docs/privacy.md](privacy.md), [submission risks](submission/risks.md).

## Configuration

Put these in `.env` in the repository root. The file is git-ignored and is not copied into the
image. `make dev` loads it into the API environment. Compose reads it for interpolation but only
forwards variables declared in `compose.yaml`: the backend gets `ANTHROPIC_API_KEY`,
`PRAWDOWID_MODEL`, `GOOGLE_FACTCHECK_API_KEY`, `TAVILY_API_KEY`, `EUVSDISINFO_API_KEY`,
`PRAWDOWID_GOVPL`, `PRAWDOWID_INCIDENTS_PATH`, `PRAWDOWID_EVAL_TOKEN` and `PRAWDOWID_ADMIN_TOKEN`, its check log and moderator cases sit on the `checklog` volume (`/var/lib/prawdowid`, kept across
deploys) and its source cache points at a writable `/tmp` path. Other tuning variables need an explicit Compose environment override.

| Variable | Required | Default | What it does |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | none | Anthropic API key. Without it every check returns `technical_error`. |
| `PRAWDOWID_MODEL` | no | `anthropic:claude-sonnet-5-5` | PydanticAI model id (`provider:model`) for claim extraction. Sonnet since 22.11 (same quick-set result as Opus, 18.3 s vs 24.9 s median, $3.96 vs $4.91 per 100 checks, #88). |
| `PRAWDOWID_EVAL_TOKEN` | no | unset | Secret for the eval-only fault switch (`X-Eval-Fault` and `X-Eval-Token` headers, scenario J: `factcheck_api_unavailable`, `llm_unavailable`). Unset: the headers do nothing. Never set it on the public demo. The eval harness reads the same variable. |
| `PRAWDOWID_MAX_CHECKED_CLAIMS` | no | `3` | Claims checked in full per input; the rest are listed as not checked. |
| `PRAWDOWID_CHECK_BUDGET_S` | no | `40` | Time budget for the whole check, in seconds. Claims still running at the end are `not_checked`. |
| `PRAWDOWID_WEB_SEARCH_BUDGET_S` | no | `10` | Longest one web search query may take, retry included, before it counts as unavailable. |
| `PRAWDOWID_PAGE_BUDGET_S` | no | `8` | Longest one page fetch may take (robots.txt and page); a slower web-search page counts only through its search snippet, labelled "fragment z wyników wyszukiwarki" ([docs/sources.md](sources.md)), a slower page from the www.gov.pl site search is skipped; the others are kept. |
| `PRAWDOWID_GOVPL` | no | `1` | `0` switches off the www.gov.pl site search (`prawdowid/govpl.py`); its queries then go to web search, which searches www.gov.pl again. See [docs/sources.md](sources.md). |
| `PRAWDOWID_QUERIES_PER_CLAIM` | no | `2` | Web search queries the extraction model writes per checked claim. The claim sentence itself and one fact-checkers-only search of it are always added, so a claim costs about 4 Tavily searches, all in parallel. |
| `PRAWDOWID_EXTRACT_THINKING`, `PRAWDOWID_RERANK_THINKING`, `PRAWDOWID_JUDGE_THINKING` | no | `low`, `false`, `low` | PydanticAI `thinking` setting of the extraction, rerank and judge agents: `false`, `minimal`, `low`, `medium` or `high`. A bad value stops the service at startup. |
| `DISCORD_BOT_TOKEN` | only for the Discord bot | none | Bot token from the Discord developer portal. Without it the bot refuses to start. |
| `PRAWDOWID_API_URL` | no | `http://127.0.0.1:8000` | API the Discord bot calls (`http://backend:8000` in Docker). |
| `GOOGLE_FACTCHECK_API_KEY` | no | none | Google API key with the Fact Check Tools API enabled. Without it the known-claim lookup is reported as unavailable, which counts as an outage: a claim without enough other evidence is then `nie sprawdzono`, not "brak wystarczających dowodów". |
| `TAVILY_API_KEY` | no | none | Tavily API key (`tavily-python`) for web search on allowlisted domains (step 2b). Without it the web search is skipped and reported as unavailable. |
| `DOMAIN` | with `compose.prod.yaml` | none | Public domain Caddy gets the HTTPS certificate for (`compose.prod.yaml`, see `docs/deploy.md`). |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | with `compose.prod.yaml` | none | Database, user and password of the `db` service. `compose.prod.yaml` passes them to the backend as `DATABASE_URL`. `POSTGRES_PASSWORD` is also the password of the local `sourcedb` service (default `prawdowid`, port bound to 127.0.0.1 only), applied only when its `sourcedb_data` volume is created; see [deletion instructions](sources.md). `make db-seed` refuses until the team approves sources for full-text storage; see [the prerequisite](sources.md#full-text-seed-approval). |
| `DATABASE_URL` | no | none | Postgres URI of the step 2c source store, used only by the seed script (`make db-seed` sets it) and `cache.search_documents`. Step 2c is disabled in the pipeline until licensed sources are chosen, so checks never read or write the database. The backend never needs it; `compose.prod.yaml` sets it for production's separate `db`, which has no source-store schema, so enabling step 2c in production needs this migration applied there first. Start the database with `make db` (127.0.0.1:5433). The corpus search (`prawdowid/corpus_search.py`) reads its own tables (`corpus_documents`, `corpus_chunks`) from the same database; `make index` builds them from `corpus/evidence.jsonl`. |
| `EUVSDISINFO_API_KEY` | no | none | Personal API key for the EUvsDisinfo MCP server (`https://mcp.euvsd.info/mcp`), generated on euvsdisinfo.eu. Sent as the `X-API-Key` header. Without it the EUvsDisinfo lookup is skipped and reported as unavailable. |
| `PRAWDOWID_CHECK_LOG` | no | `logs/checks.jsonl` | Check log file (masked question, result, session id). Docker sets `/var/lib/prawdowid/checks.jsonl` on the `checklog` volume. See [docs/privacy.md](privacy.md). |
| `PRAWDOWID_CASES` | no | `cases.jsonl` next to the check log | Moderator cases (masked claims, session id, lookups tried), with a `.seq` and a `.lock` file of the same name beside it and a `.tmp` file during each write. Docker: `/var/lib/prawdowid/cases.jsonl` on the `checklog` volume. See [docs/privacy.md](privacy.md#moderator-cases). |
| `PRAWDOWID_ADMIN_TOKEN` | no | unset | Bearer token for `GET /api/cases`, the moderator queue. Give it to the moderator or analyst the administrator names. Unset: there is no moderator queue, so no check files a case, no channel mentions a moderator and the route answers 404. Use a long random value (`openssl rand -hex 32`). |
| `PRAWDOWID_CASE_MIN_SIMILARITY` | no | `0.5` | Share of word stems (Jaccard) two claims must share to be one moderator case. A first guess, not tuned. |
| `PRAWDOWID_INCIDENTS_PATH` | no | `prawdowid/data/incidents.json` (empty) | Scenario I incident base, a `.json` or `.csv` file; format in `prawdowid/incidents.py`. Put the file in `incidents/` (git-ignored) and set a path relative to the repository root, e.g. `incidents/base.csv`: `make dev` reads it from the repository, Docker from `/app/incidents/base.csv`, where `compose.yaml` mounts `incidents/` read-only. The file must be readable by every user (the container runs as `nobody`). Read on the first check and kept: restart the backend after changing it. A match is shown next to the claims and never changes a verdict. |
| `PRAWDOWID_EMBEDDING_MODEL` | no | `intfloat/multilingual-e5-large` | Local embedding model for corpus search (fastembed). Changing it rebuilds the index on the next `make index`. |
| `FASTEMBED_CACHE_PATH` | no | fastembed's temp dir | Where the embedding model files are kept (`/models` in the image). |

The extraction call has a 45 s provider request timeout and at most one SDK retry, but shares
the 40 s whole-check deadline with URL fetching and per-claim checks, inside the API's 60 s
limit. Extraction errors and a missing model key return `technical_error`; a
model refusal returns `cannot_check`. Both carry a Polish message and no claims. Retrieval
failures are listed per claim; an outage of a source that could decide the verdict (see above) or a
judge-model outage makes the claim `not_checked`, and the whole answer a `technical_error` when no
claim has a verdict.
There is no second search pass: the claim sentence and a fact-checkers-only search of it run in the
first one.

## API

| Method and path | What it does |
|---|---|
| `POST /api/checks` | Body `{"input": "..."}`. Returns `CheckResult`. 60 s timeout on `verify`; 10 requests per minute per client IP. |
| `GET /api/cases` | The moderator queue, for the holder of `PRAWDOWID_ADMIN_TOKEN` (`Authorization: Bearer <token>`); 404 when the variable is unset, 401 on a wrong token. Not in the channel spec. |
| `GET /api/openapi.json` | The OpenAPI spec. |
| `GET /api/docs` | Interactive docs (Swagger UI) for the spec. |
| `GET /health` | Liveness. |

**Adding a channel.** The spec is the contract: https://faktczyfejk.pl/api/openapi.json, with
interactive docs at https://faktczyfejk.pl/api/docs, and a copy in
[`docs/openapi.json`](openapi.json) that needs no running server. After an API change
run `make openapi`; a test fails while the copy is stale. A channel sends `POST /api/checks`
with `X-Channel: <its name>` (a name missing from `CHANNELS` in `prawdowid/app.py` is logged
as `other`) and, to keep its checks together, the `X-Session-Id` it got back. The Discord bot
([`prawdowid/discord_bot.py`](../prawdowid/discord_bot.py)) sends `X-Channel: discord`, the demo
adapter at `/czat` ([`frontend/public/czat.js`](../frontend/public/czat.js)) `X-Channel: demo`; the web
page ([`frontend/public/app.js`](../frontend/public/app.js)) sends the session id back.

Input is trimmed and must be 1 to 5000 characters. A single token containing `://` counts as a
link and must be a valid `http` or `https` URL. The page is fetched only from public addresses
(checked on every connection, so redirects and DNS cannot reach private, loopback or link-local
hosts), with at most 3 redirects (their bodies are never read), a 10 s deadline and a 2 MB cap.
The URL policy (scheme, social media hosts, login pages) is applied before every hop. HTML goes
through trafilatura and PDF through pypdf in a child process (`prawdowid/extract_worker.py`) that
is killed at the deadline; at most 2 run at once per API process. The parsers stop after 50 PDF
pages, 20,000 characters and 20 MB decompressed per stream; on Linux the child is also capped at
1 GB of memory and 15 s of CPU. Title, publisher, date and text together are cut to 5000
characters for the verifier. `CheckResult.page` carries the
page URL, content hash, title, publisher and date, never the page text. An `input` that is
empty, too long or not a valid link comes back as 422 with a Polish message in `detail[0].msg`.

`ClaimResult` carries `verdict_label`, the Polish label for its verdict, so channels do not keep
their own copy of the labels.

**Moderator queue.** It exists only while `PRAWDOWID_ADMIN_TOKEN` is set. `GET /api/cases` lists
the open cases, the most asked first: number, opening
time, `last_seen` (the last question), `count`, `reasons` (`insufficient_evidence`,
`security_event:<where>`, `high_risk:<topic>`), the masked `claims`, `channels`, `pages`, `lookups`
(the sources tried: `factcheck`, `euvsdisinfo`, `govpl`, `web`, `corpus`) and the `sources` they
found. No session ids. Example: `curl -H "Authorization: Bearer $PRAWDOWID_ADMIN_TOKEN"
http://localhost:8080/api/cases` (`make up`). A check that filed a case carries `moderator_case`
(`id`, `status` `created` or `updated`, `count`); without it, a channel says nothing about a
moderator. `DELETE /api/sessions/{id}` also takes the session's questions out of the cases and
returns how many in `withdrawn`. What is stored and for how long:
[docs/privacy.md](privacy.md#moderator-cases).

## Layout

- `frontend/`: static `index.html` (the check) and `zrodla.html` (the source list, from
  `GET /api/sources`), with `styles.css`, `common.js`, `app.js` and `zrodla.js` (no build step), served by nginx.
  `czat.html`, `czat.js` and `czat.css` are the messenger demo adapter at `/czat` (#116): the same
  `POST /api/checks` with `X-Channel: demo`, the reply in the sections and order of the Discord bot's
  message plus the web page's first words (`tests/test_czat.py` keeps the wording in step).
  nginx also proxies `/api/` and `/health` to the backend, caps request bodies at 64 KB and sets
  a strict Content-Security-Policy (wider only for `/api/docs`, which loads Swagger UI from
  cdn.jsdelivr.net).
- `Dockerfile`: the backend image (Python 3.13, uv, runs as `nobody`).
- `compose.yaml`: both services. Only the frontend port is published.
- `compose.prod.yaml`, `caddy/Caddyfile`: production overlay. Caddy serves HTTPS in front of nginx
  and is then the only service with published ports; `db` is Postgres 18 with pgvector and pg_trgm.
- `deploy/`: the server's deploy script and systemd timer. The demo server picks up a push to the
  `prod` branch within about a minute and then builds and starts it; setup in `docs/deploy.md`.
- `prawdowid/contract.py`: `Verdict`, `Status`, `Source`, `ClaimResult`, `CheckResult` (with `page`,
  `security_events`, `cost_usd`).
- `prawdowid/privacy.py`: `mask_personal_data` and `RETENTION_DAYS`; `prawdowid/checklog.py`: the check log
  per demo session (`DELETE /api/sessions/{id}` removes a session).
- `prawdowid/cases.py`: moderator cases (scenario H). `report` files a check that needs a person
  (a claim without enough evidence, a security event, an unconfirmed claim on a high-risk topic)
  into the open case with the same or a similar claim, or opens one; `read_cases` is the admin view.
- `prawdowid/link.py`: `fetch_page(url)`, the guarded fetch and text extraction for link input.
- `prawdowid/verifier.py`: `async def verify(text) -> CheckResult`, the one function every
  channel calls. Holds the PydanticAI agent, its prompt and `to_check_result`, the pure function
  that turns the model's claims into verdicts.
- `prawdowid/factcheck.py`: `search_keys(claim, keys)`, the known-claim lookup in Google Fact
  Check Tools (`claims:search`). `keys_for` gives each claim several short keys (the claim, the
  names in it, quoted spans of the claim or its source sentence, its search queries; masked again,
  at most `PRAWDOWID_FACTCHECK_MAX_KEYS`, 8), sent at once and merged by review URL, at most 10
  reviews. Each review becomes a `Source` (`source_type="fact_check"`) whose fragment carries the
  fact-checker's rating and the reviewed claim as data for the judge. A rating sets the verdict
  only for a review of the checked claim itself (`judge.RATINGS`, ADR 0001); a review of another
  claim is context. One retry on a network error or 5xx, 15 s deadline per key. A missing key,
  4xx (bad key, quota) or outage of a key is a `limitation`; Fact Check counts as down when the
  claim's own key or every key failed. Called per claim from `prawdowid/pipeline.py` (#11, #100).
- `prawdowid/corpus_bm25.py`: `search_evidence(queries)`, the corpus lookup of every check, in step 2
  next to Fact Check, EUvsDisinfo, gov.pl and web search. BM25 in memory over
  `corpus/evidence.jsonl` (`bm25s`, numpy only): no database, no embedding model, no network. The
  API builds the index at startup (0.7 s on a laptop, 1,158 records; a lookup that comes first
  builds it); a lookup takes about a millisecond. Words are lowercased, stripped of diacritics and cut to five letters,
  stopwords dropped. The claim and each of its queries are ranked on their own and merged by
  reciprocal rank fusion: at most 5 documents, 2 passages of each. A hit is a `Source` with the
  record's publisher, publication date and retrieval date, and a `fragment` that is a verbatim
  part of the document, so the judge's quote check works as for any other source. A missing or
  unreadable file returns a `limitation`; a line that is no record is skipped. When every outside source fails, corpus hits count only
  if the judge settles the claim on them; otherwise the claim is `nie sprawdzono`. Try it:
  `uv run python -m prawdowid.corpus_bm25 "czy MSZ odradza podróże do Izraela"`.
- `prawdowid/corpus_search.py`: `search_corpus(query)`, hybrid search in the evidence corpus
  (pgvector nearest chunks and Postgres full-text, merged by reciprocal rank fusion, at most two
  chunks per document). Each hit is a `Source` whose `fragment` is a verbatim chunk of the stored
  document, plus the fact-checker's rating and reviewed claim for fact-checks. 10 s deadline; no
  database or an error returns a `limitation`. Checks do not call it, they use `corpus_bm25.py`.
  `prawdowid/index.py` builds the tables (`make index`), `prawdowid/embeddings.py` holds the
  local embedding model.
- `prawdowid/app.py`: the API, input validation, rate limit, the `technical_error` path and the
  OpenAPI docs (`docs/openapi.json` is its committed spec).
- `prawdowid/discord_bot.py`: the second channel, a `/sprawdz tekst:` slash command (discord.py).
  It sends the same `POST /api/checks` as the web form, with `X-Channel: discord`, and renders the
  `CheckResult` with the same sections (verdict, reasoning, strength, premises, sources with
  quotes, limitations). User and source text is escaped and messages never ping anyone. An answer
  goes out in at most 5 messages of 2000 characters; whatever does not fit is in an attached
  `odpowiedz.md` with the whole answer. API errors are shown as notices.
  The bot shares one API rate limit (10 per minute) for all its users.
- `corpus/`: the evidence corpus. `catalog.yaml` is the audited source list with its rules,
  `evidence.jsonl` the collected records, `manifest.json` the last build, `build.py` and `sources/`
  the collectors. Sources, licences and limits: [`docs/corpus.md`](corpus.md).

