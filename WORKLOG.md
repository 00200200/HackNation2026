# Worklog

Shared state of the project for people and agents. Read it before starting work; update it when you
finish a task, open or merge a branch, or change a decision. Keep "Now" and "Next" true; append to
"Log" (newest first). Facts only: link commits, branches and eval runs; mark guesses UNCONFIRMED.

Challenge: Prawdowid (MSZ) at HackNation 2026. Submission closes **22.11.2026 11:00**.
Rules and jury criteria: `.claude/skills/hacknation-judging/SKILL.md`. Metrics: `.claude/skills/prawdowid-eval/SKILL.md`.

## Now (snapshot, edit in place)

Updated: 2026-11-21, by Łukasz (Claude worker).

**Works end to end:** web form (nginx, `frontend/`) → `POST /api/checks` (FastAPI, `prawdowid/app.py`) →
`verify()` (`prawdowid/verifier.py`) → PydanticAI agent on Claude splits the text into claims marked checkable or
not → verdict set in code. No sources yet, so every checkable claim is `brak wystarczających dowodów` and the rest
`nie podlega weryfikacji`. Links (#4, branch `LukiLenkiewicz/issue4-link-input`): fetched safely (`prawdowid/link.py`), main text goes through the same `verify()`; blocked pages, paywalls, social media, private addresses and non-HTML/PDF files return `cannot_check` with a request to paste the text. Nothing is stored; each link check logs URL, content hash, claims and result to stdout.

**Branches**

| Branch | State |
|---|---|
| `main` / `origin/main` | at `7ee1410`: skeleton (#1), pre-push gate, PydanticAI verifier (#2), worklog and eval results (#3). |
| `feat/7-search-provider` | #7 search provider research, WORKLOG only. PR open, not merged. Owner: Łukasz (Claude worker). |
| `feat/8-web-search` | #8 web search (DuckDuckGo via `ddgs`), page fetch, source cache, `docs/sources.md`. Stacked on `LukiLenkiewicz/issue9-rerank`, PR open, not merged. Corpus not built. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue19-supabase` | #19 step 2c: local PostgreSQL source store (compose `sourcedb`) and per-claim full-text search, stacked on `LukiLenkiewicz/issue31-euvsdisinfo` (#33). PR open, not merged. **Disabled in the pipeline** (user decision). Database empty, not seeded. Owner: Łukasz (Claude worker). |
| `feat/16-eval-set` | #16 eval set (31 cases) and full eval, stacked on `feat/5-self-contained-claims`. PR open, not merged. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue9-rerank` | #9 step 3 rerank and dedupe, stacked on `LukiLenkiewicz/issue13-discord` (PR #24). PR open, not merged. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue31-euvsdisinfo` | #31 EUvsDisinfo MCP lookup, stacked on the stack tip. PR open, not merged. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue10-judge` | #10 steps 4 and 5 judge with quotes and verdict rules, stacked on `LukiLenkiewicz/issue4-link-input` (PR #28). PR open, not merged. Owner: Łukasz (Claude worker). |
| `origin/feat/service-skeleton`, `origin/tooling/judge-eval-gate` | already in `main` (squashed). Safe to delete after a team OK. |

**Last eval** (`evals/results/latest.json`, **quick**, 8 cases, product at `ba48fc7` on this branch, no corpus):
macro_f1 0.111 (fail, target ≥ 0.75), abstention 1.00, injection_resistance 0.00 (fail), median latency 4.8 s,
end_to_end 0.875 (fail), $1.60 per 100 checks. Citation metrics and channel consistency: not measured (no corpus, no
second channel). Earlier runs (the 31-case full run at `d655078`, quick runs at `88ae501` and `dd0a976`) are historical.

**Architecture board:** https://claude.ai/artifact/W9KUaX37YHjRFjAzZedyvs (also linked from README).

## Next (open work, take one and put your name on it)

Basic requirements first: the jury gives no points for extras if one of these is missing.

- [x] Merge `feat/llm-verifier` into `main` (#2, #3). Owner: Łukasz
- [x] Step 1 (#5): self-contained claims, quote split, search queries per claim, top N checked, rest listed as not checked. Owner: Łukasz (Claude worker), branch `feat/5-self-contained-claims`, PR stacked on `feat/6-factcheck`, in review.
- [ ] Demo corpus: ≥ 100 documents, ≥ 10 domains, ≥ 2 source types, publication and retrieval dates. Owner: Łukasz (Claude worker)
  - [x] Code (#8): `prawdowid/websearch.py` (search on the allowlist, fetch, trafilatura extraction, PII masking of the query), `prawdowid/cache.py` (local JSONL, swap point for #19), builder `python -m prawdowid.corpus`, source list `docs/sources.md` (licences UNCONFIRMED). Branch `feat/8-web-search`.
  - [ ] Build the corpus: **open**. DuckDuckGo (`ddgs`, backend `duckduckgo`) returned "No results found" for every query from our machine on 2026-11-21, so 0 documents are cached. Needs the replacement provider (#7), then `uv run python -m prawdowid.corpus`.
- [ ] Retrieval and evidence: sources with title, publisher, date, URL, quote; verdicts beyond "no evidence". Owner: ?
  - [x] Step 2a (#6): Google Fact Check `claims:search` lookup, `prawdowid/factcheck.py`, branch `feat/6-factcheck`. Not wired into `verify()` (#11). Polish coverage and `pl` vs no language filter: not measured, no key yet. Owner: Łukasz (Claude worker)
  - [ ] Step 2c (#19): code done, **disabled in the pipeline** until licensed sources are chosen (user decision): not wired into `verify()`, checks never read or write the database. Local PostgreSQL 17 (compose service `sourcedb` behind profile `sourcedb`, named volume `sourcedb_data`, port on 127.0.0.1:5433, `make db`, `make db-migrate`, `make db-seed`). Schema `db/migrations/001_source_store.sql` (`documents` with licence, content hash and `delete_after` retention, `chunks` with a `simple` tsvector and GIN index, `delete_expired_documents()`), applied on first start of the volume. `prawdowid/cache.py` (psycopg 3, `DATABASE_URL`): `store_document` / `stored_documents` for the seed only; `search_documents(claim)` returns one `Fragment` (doc id = canonical URL, `Source` with joined matching chunks) per document for rerank (at most `CHUNKS_PER_DOCUMENT` = 2 chunks per document, then the best `limit` documents, so one long page cannot crowd out the rest), or the limitation "baza źródeł niedostępna" when the database is missing, fails or is slow (4 s connect, 4 s statement, TCP keepalive, 15 s deadline, one retry). Web search keeps saving to `corpus/docs.jsonl` only (saves capped at 10 s per search). Seed: `corpus/queries.txt` through `make db-seed` (reads `.env`, URI from `POSTGRES_PASSWORD`/`DB_PORT`); refuses until the team records approvals in `APPROVED_SOURCES` (currently empty), checks final hosts and stores the approved licence; it writes only metadata (`corpus/manifest.jsonl`), never page text, so database retention and deletion cover every copy. A citation eval against database content needs a retention-aware export, left for when 2c is enabled. **Not seeded on purpose.** Linked pages (#4) never saved. Open: licensed sources decision, then wire `search_documents` at #11's 2c call site; seed run; retention period (#17). Owner: Łukasz (Claude worker)
  - [x] Step 3 (#9): `prawdowid/rerank.py`, per claim: drops the linked page (`exclude_url`) and repeated canonical URLs, splits page text into fragments of ≤ `PRAWDOWID_FRAGMENT_CHARS` (800), drops near-duplicates (word-trigram Jaccard ≥ 0.8), interleaves documents and sends at most `PRAWDOWID_RERANK_MAX_FRAGMENTS` (60), Claude Haiku via PydanticAI orders them, top `PRAWDOWID_RERANK_TOP_K` (12) kept with `doc_id` = canonical URL. Model failure or no key: unranked order plus a limitation. Not wired into `verify()` (#11). Ranking quality not measured, no key yet. Owner: Łukasz (Claude worker)
  - [x] Step 2c (#31): EUvsDisinfo MCP `search` lookup, `prawdowid/euvsdisinfo.py`: pydantic-ai `MCPToolset` (Streamable HTTP, `X-API-Key` from `EUVSDISINFO_API_KEY`), 8 s connect and 8 s per read, 15 s deadline over everything, one retry (it only fits after a fast failure; a slow first attempt uses up the deadline). Hits on euvsdisinfo.eu become `Source` (`official`, publisher EUvsDisinfo (ESDZ)) with `published_at=None` because `search` returns no date. A match is context for the judge, never a verdict. Missing or bad key, error or timeout: limitation. Not wired into `verify()` (#11, plugs in next to `factcheck.search_claims` before `rerank`); #12 incident warning not in base. No key yet, so no live search run; with a dummy key the real server answered 401 and the lookup returned the limitation in 0.5 s. Branch `LukiLenkiewicz/issue31-euvsdisinfo`. Owner: Łukasz (Claude worker)
  - [x] Steps 4 and 5 (#10): `prawdowid/judge.py`. Claude Sonnet via PydanticAI labels each reranked fragment supports/refutes/context with an exact quote, `doc_id` and the missing context it names; code drops quotes whose words (≥ 3, in order, whole words; case and punctuation ignored) are not in the title or fragment of the cited document, shows the document's own span, ignores a publisher that labels both sides and sets the verdict in `decide()` (table in its docstring). Model failure or no key: `brak wystarczających dowodów` plus a limitation. Not wired into `verify()` (#11), so scenarios A–D in the quick eval are not measured yet. Owner: Łukasz (Claude worker)
- [x] Second channel (#13): Discord `/sprawdz` bot, `prawdowid/discord_bot.py`, calls the same `POST /api/checks` with `X-Channel: discord`, branch `LukiLenkiewicz/issue13-discord`. Not run against real Discord (token not used by the worker); eval `channel_consistency` needs `PRAWDOWID_EXTRA_CHANNELS=discord` and multi-channel cases. Owner: Łukasz (Claude worker)
- [x] Real eval set `evals/cases.jsonl`: 31 cases, scenarios A–E, G, I, J at least twice, labels from Demagog, Konkret24, EUvsDisinfo. Owner: Łukasz (Claude worker). Open: I cases use EUvsDisinfo, not the organiser's incident base (not available to us); EUvsDisinfo blocks automated fetch, so check I01–I03 labels by hand; J cases need a product eval switch to simulate a missing key or limit.
- [x] Contract gaps for metrics (#15): `security_events` (the extraction call flags instructions aimed at the model; event carries no wording) and `cost_usd` per answer (token usage priced by genai-prices through PydanticAI; 0.0 when no request was sent, null when unknown). Web and Discord show a notice when an event is logged. Not measured with a real key yet. Branch `LukiLenkiewicz/issue15-contract-metrics`. Owner: Łukasz (Claude worker)
- [x] Link input (#4): safe fetch (http/https, SSRF guard on every connection incl. redirects and DNS, ≤ 3 redirects, 10 s, 2 MB, HTML via trafilatura, PDF via pypdf), page URL kept in `CheckResult.page` for later evidence exclusion. Branch `LukiLenkiewicz/issue4-link-input`, stacked on #15, in review. Prompt injection found in a page is logged with `location="page"`. Owner: Łukasz (Claude worker). Open: page text cut to 5000 chars (same as pasted text, UNCONFIRMED choice); no eval case uses a URL yet.
- [ ] Privacy: mask obvious personal data, retention, deletable demo session. Owner: ?
- [ ] Deliverables: description ≤ 4000 chars, PDF ≤ 12 slides, video ≤ 3 min, cost estimate, risks. Owner: ?
- [ ] Optional after basics: moderator loop (scenario H), screenshots (F).
- [ ] Team OK on the web search provider (PROPOSED below, #7); then run ~20 Polish test queries once a key exists. Owner: Łukasz (Claude worker)

## Decisions

- 2026-11-21: **User decision:** step 2c disabled until licensed sources are chosen. The #19 store, migration, compose service and seed script stay in the repo, but `verify()` does not call `search_documents`, checks never write to the database, and the backend runs without Postgres. (#19)
- 2026-11-21: **User decision:** step 2c uses a local PostgreSQL (compose service `db`, renamed `sourcedb` after the PR #34 review), not Supabase. Driver psycopg 3 on `DATABASE_URL` (researcher check: one transaction for a document and its chunks, one SQL search query). Full-text search only: `simple` config (stock Postgres 17 has no Polish config, checked in `pg_ts_config`) plus prefix terms built in code as a crude stem. pgvector and the embedding model stay UNDECIDED. The database starts empty; the team seeds it after merge. (#19)
- 2026-11-21: Verdict rules (#10, `judge.decide`). A side counts when one `official`/`primary`/`fact_check` source or two independent origins back it with a verified quote. Origins: evidence sharing a publisher, the same quote or a named news agency (PAP, Reuters, ...) counts once. A publisher on both sides keeps the side the model marks as its own conclusion, else neither. Missing context counts only on a context/refute label whose verified quote shares a number or word with it. Quotes match with typography, case and spacing folded; digits, signs and separators exact. Both sides count: `brak wystarczających dowodów`, conflict shown (scenario C). Named missing context counts: `wprowadzające w błąd` (B). Else refute: `fałszywe`, support: `potwierdzone`, nothing: `brak wystarczających dowodów`. Sources older than `PRAWDOWID_ARCHIVE_DAYS` (730) get an archival warning. Thresholds are UNCONFIRMED guesses; corpus source-type labels are not fixed yet.
- 2026-11-21: Web search starts with **DuckDuckGo** through `ddgs` (backend `duckduckgo` only, no `auto` fallback to
  other engines), user decision; the Tavily proposal (#7) stays as the later replacement. DuckDuckGo has no official
  web search API (`ddgs` scrapes), which conflicts with the brief's rule on official APIs: needs a team OK before
  submission. The provider is one function (`SearchProvider` in `prawdowid/websearch.py`), so a Tavily wrapper is one
  new function. (#8)

- 2026-11-21: Verdicts are per claim. One extraction call returns ranked, self-contained claims with a source sentence and search queries; the top `PRAWDOWID_MAX_CHECKED_CLAIMS` (default 5) come in full (source sentence, reason, queries) and get a verdict; every other claim comes as one short sentence in `unchecked_claims`, no verdict. Full detail for all claims took 83 s on a 4837-char text; this shape took 30.8 s. Queries per claim: `PRAWDOWID_QUERIES_PER_CLAIM` (default 3). Defaults are UNCONFIRMED guesses, not tuned. (#5)
- 2026-11-21: **PROPOSED, needs team OK** (#7). Web search for step 2b: **Tavily** `/search` as the provider, called
  with `include_domains` (allowlist, `include_domains_mode=restrict`) and `language="pl"`, through the official
  `tavily-python` SDK. Fallback on the same contract: **Exa** (`exa-py`, `includeDomains`, `userLocation="PL"`).
  Sources checked 2026-11-21. Reasons:
  - Official API, signup open, free tier of 1,000 credits a month without a card, which covers the demo and evals
    ([credits](https://docs.tavily.com/documentation/api-credits)).
  - Native domain allowlist, up to 300 domains, plus an ISO language filter
    ([search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)). Brave has only `site:` and
    Goggles ([docs](https://api-dashboard.search.brave.com/app/documentation/web-search/query)).
  - Exa is cheaper ($4 per 1k Lite, $10 free a month) and allows 1,200 domains, but has no language parameter
    ([pricing](https://exa.ai/pricing), [search](https://docs.exa.ai/reference/search)). It is a good fallback.
  - Ruled out: Bing Search APIs were retired on 2025-08-11 and take no new signups
    ([notice](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)). Its successor,
    Grounding with Bing, returns an LLM answer and sends data outside the Azure compliance boundary
    ([docs](https://learn.microsoft.com/en-us/azure/foundry-classic/agents/how-to/tools-classic/bing-grounding)). Google Custom
    Search JSON API is "closed to new customers" and shuts down on 2027-01-01
    ([overview](https://developers.google.com/custom-search/v1/overview)). SerpApi-style scrapers break the brief's
    ban on bypassing site protections.
  - EEA: none of Tavily, Exa or Brave documents EU data residency. Tavily states GDPR and SOC 2
    ([help](https://help.tavily.com/articles/6781493822-data-retention)). Nebius agreed to buy Tavily on 2026-02-10
    ([Nebius](https://nebius.com/newsroom/nebius-announces-agreement-to-acquire-tavily-to-add-agentic-search-to-its-ai-cloud-platform));
    whether the deal closed and where data is processed are UNCONFIRMED. An Exa EU region in Stockholm is UNCONFIRMED
    (secondary sources only). Mojeek runs its own European infrastructure (£2–3 per 1k,
    [API](https://www.mojeek.com/services/search/web-search-api/)), but its Polish coverage is UNCONFIRMED and its
    country, likely the UK, is not in the EEA. We state this as a limitation in the deliverables.
  - Polish result quality and latency: UNCONFIRMED. No search API key is in the environment, so no test queries were run.
  - Cost for 1,000 checks, **assuming 3 queries per check** (about 3 checkable claims, 1 basic search each):
    3,000 queries. Tavily pay-as-you-go at $0.008 a credit costs **$24**, or $16 after the 1,000 free monthly credits.
    Exa Lite costs about $12 and Brave at $5 per 1k
    ([pricing](https://brave.com/search/api/)) costs $15. The `advanced` depth costs 2 credits, which doubles the
    Tavily figure. LLM cost is not included.
- 2026-11-21: The model never decides truth. It extracts claims; verdicts are set in code from evidence. (`b52c248`)
- 2026-11-21: Model through PydanticAI, default `anthropic:claude-opus-5-5`, swappable with `PRAWDOWID_MODEL`. (`b52c248`)
- 2026-11-21: No database for now; each check is logged to stdout. Storage UNDECIDED. (`96f3b46`)
- 2026-11-21: Frontend is static HTML/CSS/JS behind nginx, no build step; backend is JSON only. (`96f3b46`)
- 2026-11-21: Every push goes through `.githooks/pre-push` (ruff, pytest, eval, judge PASS). (`d5aa35b`)

## Log (newest first, append only)

- 2026-11-21 Łukasz (Claude worker): PR #34 review fixes on `ba48fc7` checked: production overlay (`compose.yaml` + `origin/main:compose.prod.yaml`) renders `db backend frontend caddy` with the production `db` unchanged, 220 passed / 1 skipped; quick eval on `ba48fc7` (macro_f1 0.111, injection 0.0, end_to_end 0.875, 4.8 s, $1.60 per 100).
- 2026-11-21 Łukasz (Codex worker): PR #34 scoped review fixes (`ba48fc7`): isolated local `sourcedb`/`sourcedb_data` from production, required source approval before database seeding, removed connection error text from diagnostics; added failing-before/passing-after tests and `.env` recipe regression coverage. Checks: Ruff clean, 220 passed / 1 skipped; production overlay renders with unchanged database settings.
- 2026-11-21 Łukasz (Claude worker): #19 PR #34 Codex review fixes: per-document chunk cap before the document limit (regression test, passes on Postgres 17, old SQL returned only the long page), seed reads `.env` (`--local-db`), no full-text export of the database.
- 2026-11-21 Łukasz (Claude worker): #19 merged `origin/LukiLenkiewicz/issue31-euvsdisinfo` (#33) to keep the stack linear; kept the newer quick eval (8 cases, 17:23 UTC) over the older full run from #31's base; quick eval rerun on the merge: macro_f1 0.111, injection 0.0, end_to_end 0.875, latency 3.4 s, $1.50 per 100.
- 2026-11-21 Łukasz (Claude worker): #19 step 2c taken out of the pipeline (user decision): only the seed script writes to the database, web search saves to JSONL only, compose `db` is opt-in (profile `db`), backend has no `DATABASE_URL`. Branch `LukiLenkiewicz/issue19-supabase`.
- 2026-11-21 Łukasz (Claude worker): #19 source store on local PostgreSQL (user decision, replaces Supabase): compose `db`, migration, psycopg store behind `cache.py`, per-claim FTS, seed queries file, retention, offline tests, checked on Postgres 17. Not seeded. Branch `LukiLenkiewicz/issue19-supabase`.
- 2026-11-21 Łukasz (Claude worker): #31 `prawdowid/euvsdisinfo.py` EUvsDisinfo MCP `search` lookup (pydantic-ai MCP client), offline tests against an in-process FastMCP server. Branch `LukiLenkiewicz/issue31-euvsdisinfo`.
- 2026-11-21 Łukasz (Claude worker): #10 PR #30 review fixes: fact-check debunk keeps its own conclusion, grounded missing context, syndicated copies one origin, exact numbers in quotes, `security_events` (location `source`) for injection in retrieved fragments.
- 2026-11-21 Łukasz (Claude worker): #10 `prawdowid/judge.py` steps 4 and 5, model labels with quotes, verdict rules in code, offline FunctionModel tests per rule. Branch `LukiLenkiewicz/issue10-judge`.
- 2026-11-21 Łukasz (Claude worker): #4 link input: `prawdowid/link.py`, `CheckResult.page`, offline tests `tests/test_link.py`.
- 2026-11-21 Łukasz (Claude worker): #15 `security_events` and `cost_usd` in `CheckResult`, offline FunctionModel tests; quick eval without an API key now reports injection_resistance and cost_per_100_usd instead of unknown. Branch `LukiLenkiewicz/issue15-contract-metrics`.
- 2026-11-21 Łukasz (Claude worker): #8 web search (DuckDuckGo via `ddgs`), fetch, trafilatura extraction, JSONL source cache, `docs/sources.md`, offline tests. Corpus not built (DDG returns no results here). Branch `feat/8-web-search`.
- 2026-11-21 Łukasz (Claude worker): #9 `prawdowid/rerank.py` dedupe and rerank of evidence per claim (Claude Haiku listwise, stdlib dedupe), offline FunctionModel tests. Branch `LukiLenkiewicz/issue9-rerank`.
- 2026-11-21 Łukasz (Claude worker): #13 merged `origin/feat/16-eval-set` (stack tip) into `LukiLenkiewicz/issue13-discord` (`59c3eaf`); Discord renders `kind`, `source_sentence` and `unchecked_claims` like the web form. Quick eval without an API key: every case `technical_error`, not committed.
- 2026-11-21 Łukasz (Claude worker): #13 Discord bot (discord.py 2.7.1) on the same API and `verify()`, offline formatter and web/Discord consistency tests, `make discord`, compose profile `discord`. Branch `LukiLenkiewicz/issue13-discord`.
- 2026-11-21 Łukasz (Claude worker): #16 `evals/cases.jsonl` with 31 labelled cases, full eval on `7ee1410` committed (macro_f1 0.09).
- 2026-11-21 Łukasz (Claude worker): #16 merged `feat/5-self-contained-claims` (stack), full eval rerun on `d655078`: macro_f1 0.09, median latency 5.0 s.
- 2026-11-21 Łukasz (Claude worker): #5 claims stand alone (pronouns, relative dates from the text), quotes split into attribution + quoted, queries per claim, top-N cap with `unchecked_claims`, source sentence shown in the UI. Branch `feat/5-self-contained-claims`.
- 2026-11-21 Łukasz (Claude worker): #6 review fixes on PR #21: 15 s overall deadline for the Fact Check lookup (httpx2 timeouts are per read), reviewed claim no longer in `Source.fragment` or title.
- 2026-11-21 Łukasz (Claude worker): #6 `prawdowid/factcheck.py`, Google Fact Check lookup with offline MockTransport tests; `httpx2` moved to runtime deps. Branch `feat/6-factcheck`.
- 2026-11-21 Łukasz (Claude worker): #7 search provider research; Tavily PROPOSED in Decisions, needs team OK. Branch `feat/7-search-provider`.
- 2026-11-21 Łukasz: linked the architecture board in README, committed the quick eval on `c27b642`, pushed `feat/llm-verifier`.
- 2026-11-21 Łukasz: added this worklog and the CLAUDE.md rule to keep it current.
- 2026-11-21 Łukasz: `c27b642` prompt keeps injected instructions out of claims, checks yes/no questions.
- 2026-11-21 Łukasz: `b52c248` PydanticAI agent as the verifier, offline tests with FunctionModel. Quick eval run.
- 2026-11-21 Michał: `d5aa35b` pre-push gate, `judge` agent, jury rules, eval harness (`evals/`).
- 2026-11-21 Łukasz: `96f3b46` (#1) service skeleton: contract, stub verifier, nginx frontend, Docker, Makefile.
- 2026-11-21 Michał: `db1f374` Claude Code setup (skills, agents, settings) and uv project.
