# Worklog

Shared state of the project for people and agents. Read it before starting work; update it when you
finish a task, open or merge a branch, or change a decision. Keep "Now" and "Next" true; append to
"Log" (newest first). Facts only: link commits, branches and eval runs; mark guesses UNCONFIRMED.

Challenge: Prawdowid (MSZ) at HackNation 2026. Submission closes **22.11.2026 11:00**.
Rules and jury criteria: `.claude/skills/hacknation-judging/SKILL.md`. Metrics: `.claude/skills/prawdowid-eval/SKILL.md`.

## Now (snapshot, edit in place)

Updated: 2026-11-21 20:35, by Michał (via Claude).

**Works end to end:** web form (nginx, `frontend/`) → `POST /api/checks` (FastAPI, `prawdowid/app.py`) →
`verify()` (`prawdowid/verifier.py`) → PydanticAI agent on Claude splits the text into claims marked checkable or
not → verdict set in code. No sources yet, so every checkable claim is `brak wystarczających dowodów` and the rest
`nie podlega weryfikacji`. Links (#4, branch `LukiLenkiewicz/issue4-link-input`): fetched safely (`prawdowid/link.py`), main text goes through the same `verify()`; blocked pages, paywalls (incl. inline sign-in or subscribe walls), social media, URLs with a login or password, private addresses and non-HTML/PDF files return `cannot_check` with a request to paste the text. Nothing is stored; each link check logs URL (secret query values, userinfo and fragment redacted, also in the answer), content hash, claims and result to stdout.

**Branches**

| Branch | State |
|---|---|
| `main` / `origin/main` | at `75c1583`: skeleton (#1), verifier (#2), worklog (#3), web UI and eval set (#29), Tavily proposal (#20), Fact Check lookup (#21), deploy config (#32), self-contained claims (#22), FC eval cases (#23), pitch-deck web UI (#35). |
| `feat/ui-frontend` | merged into `main` as #29. |
| `feat/7-search-provider` | #7 search provider research, WORKLOG only. Merged into `main` as #20. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue9-rerank` | #9 step 3 rerank and dedupe, PR #25 against `main` (#24 merged). PR open, not merged. Owner: Łukasz (Claude worker). |
| `feat/8-web-search` | #8 web search (DuckDuckGo via `ddgs`), page fetch, source cache, `docs/sources.md`. PR #26 against `main` (#25 merged), PR open, not merged. Corpus not built. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue31-euvsdisinfo` | #31 EUvsDisinfo MCP lookup, PR #33 rebased onto `main` (independent of #28 and #30). PR open, not merged. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue10-judge` | #10 steps 4 and 5 judge with quotes and verdict rules, stacked on `LukiLenkiewicz/issue4-link-input` (PR #28, restacked on `main` `ebfcf76`). PR open, not merged. Owner: Łukasz (Claude worker). |
| `origin/feat/service-skeleton`, `origin/tooling/judge-eval-gate` | already in `main` (squashed). Safe to delete after a team OK. |
| `claude/deploy-config-43a484` | Deploy config, merged into `main` as #32. |
| `claude/pull-deploy` | Deploy by pulling `prod` on the server (`deploy/`), Actions workflow removed. |
| `prod` | What runs on https://faktczyfejk.pl. Only takes commits already on `main` (`docs/deploy.md`). |

**Last eval** (`evals/results/latest.json`, **full, no corpus**, 30 scored cases from `evals/cases.jsonl`, J01–J02 skipped,
commit `3ce9bae`). Does **not** count for submission: the cache-corpus run is blocked (no corpus yet) and `coverage_ok` is false
(J skipped). macro_f1 0.09 (fail, target ≥ 0.75), abstention 1.00, injection_resistance 0.00 (fail: no `security_events`,
verdicts wrong), median latency 4.1 s, end_to_end 1.00. Citation metrics, channel consistency and cost: not measured (no corpus,
no second channel, no `cost_usd`). Every checkable case returns `brak wystarczających dowodów`, so abstention 1.00 shows nothing
yet.

**Architecture board:** https://claude.ai/artifact/W9KUaX37YHjRFjAzZedyvs (also linked from README).

## Next (open work, take one and put your name on it)

Basic requirements first: the jury gives no points for extras if one of these is missing.

- [x] Merge `feat/llm-verifier` into `main`: done as #2 (`390d483`). Owner: Łukasz
- [x] Step 1 (#5): self-contained claims, quote split, search queries per claim, top N checked, rest listed as not checked. Owner: Łukasz (Claude worker), branch `feat/5-self-contained-claims`, PR #22, merged into `main`.
- [ ] Deployment: public demo on https://faktczyfejk.pl. Server (OVHcloud VPS-2, Limburg) and domain (OVHcloud)
  bought; DNS A records for the domain and `www` point at the server. The stack (Caddy, nginx, API, Postgres) runs
  there from `prod` (#32), HTTPS checked from outside. Deploys: the server pulls `prod` every minute
  (`claude/pull-deploy`, replaces the Actions workflow); its read-only deploy key `faktczyfejk-vps` is in GitHub.
  Open: Anthropic key in the server's `.env`, the timer on the server once this is on `prod` (`docs/deploy.md`).
  Owner: Michał
- [ ] Demo corpus: ≥ 100 documents, ≥ 10 domains, ≥ 2 source types, publication and retrieval dates. Owner: Łukasz (Claude worker)
  - [x] Code (#8): `prawdowid/websearch.py` (search on the allowlist, fetch, trafilatura extraction, PII masking of the query), `prawdowid/safefetch.py` (per-hop allowlist, public-IP check pinned at connect, robots.txt per hop, byte caps; for #4 to reuse), `prawdowid/cache.py` (local JSONL, metadata only until a licence is confirmed, 30-day retention, delete, swap point for #19), builder `python -m prawdowid.corpus`, source list `docs/sources.md` (licences UNCONFIRMED). Branch `feat/8-web-search`.
  - [ ] Build the corpus: **open**. DuckDuckGo (`ddgs`, backend `duckduckgo`) returned "No results found" for every query from our machine on 2026-11-21, so 0 documents are cached. Needs the replacement provider (#7), then `uv run python -m prawdowid.corpus`.
- [ ] Retrieval and evidence: sources with title, publisher, date, URL, quote; verdicts beyond "no evidence". Owner: ?
  - [x] Step 2a (#6): Google Fact Check `claims:search` lookup, `prawdowid/factcheck.py`, branch `feat/6-factcheck`. Not wired into `verify()` (#11). Polish coverage and `pl` vs no language filter: not measured, no key yet. Owner: Łukasz (Claude worker)
  - [x] Step 3 (#9): `prawdowid/rerank.py`, per claim: drops the linked page (`exclude_url`) and repeated canonical URLs (IDNA host, NFC, percent-encoding normalised; fetched text wins over a title-only hit for the same URL), reads at most `PRAWDOWID_RERANK_MAX_DOCUMENTS` (30) documents × `PRAWDOWID_RERANK_MAX_DOC_CHARS` (20k), splits page text into fragments of ≤ `PRAWDOWID_FRAGMENT_CHARS` (800), drops only exact duplicates (same words; a changed number, date or negation keeps both), interleaves documents and sends at most `PRAWDOWID_RERANK_MAX_FRAGMENTS` (60), Claude Haiku via PydanticAI orders them, top `PRAWDOWID_RERANK_TOP_K` (12) kept with `doc_id` = canonical URL. Model failure or no key: unranked order plus a limitation. Not wired into `verify()` (#11). Ranking quality not measured, no key yet. Owner: Łukasz (Claude worker)
  - [x] Steps 4 and 5 (#10): `prawdowid/judge.py`. Claude Sonnet via PydanticAI labels each reranked fragment supports/refutes/context with an exact quote, `doc_id` and the missing context it names; code drops quotes whose words (≥ 3, in order, whole words; case and punctuation ignored) are not in the title or fragment of the cited document, shows the document's own span, ignores a publisher that labels both sides and sets the verdict in `decide()` (table in its docstring). Model failure or no key: `brak wystarczających dowodów` plus a limitation. Not wired into `verify()` (#11), so scenarios A–D in the quick eval are not measured yet. Owner: Łukasz (Claude worker)
  - [ ] Step 2c (#19): local PostgreSQL source store (`db/migrations/001_source_store.sql`, compose service `sourcedb` on 127.0.0.1:5433, `make db`, `make db-migrate`, `make db-seed`), `cache.store_document` / `search_documents` with psycopg 3, full-text search (`simple` config, prefix terms). Taken from PR #34 onto `main` alone (branch `feat/19-local-source-store`). Disabled in the pipeline; database is empty. Seed blocked: no approved sources (`APPROVED_SOURCES` in `prawdowid/corpus.py`, see `docs/sources.md`) and DuckDuckGo times out (2026-11-21). Owner: Łukasz (Claude worker)
  - [x] Step 2c (#31): EUvsDisinfo MCP `search` lookup, `prawdowid/euvsdisinfo.py`: pydantic-ai `MCPToolset` (Streamable HTTP, `X-API-Key` from `EUVSDISINFO_API_KEY`), 8 s connect and 8 s per read, 15 s deadline over everything, one retry (none on a bad key; it only fits after a fast failure, a slow first attempt uses up the deadline). Hits on euvsdisinfo.eu become `Source` (`official`, publisher EUvsDisinfo (ESDZ)) with `published_at=None` because `search` returns no date. A match is context for the judge, never a verdict. Missing or bad key, error or timeout: limitation. Not wired into `verify()` (#11, plugs in next to `factcheck.search_claims` before `rerank`); #12 incident warning not in base. Live check with a real key on 2026-11-21: the server wraps hits as `{"results": [...], paging}` and returns HTML `content`; both handled on branch `fix/euvsdisinfo-live-response` (5 hits in ~2 s for "NATO biolabs Ukraine"). Polish queries return loosely related English articles, no `claim_review` hit seen yet. Branch `LukiLenkiewicz/issue31-euvsdisinfo`. Owner: Łukasz (Claude worker)
- [x] Second channel (#13): Discord `/sprawdz` bot, `prawdowid/discord_bot.py`, calls the same `POST /api/checks` with `X-Channel: discord`, branch `LukiLenkiewicz/issue13-discord`. Not run against real Discord (token not used by the worker); eval `channel_consistency` needs `PRAWDOWID_EXTRA_CHANNELS=discord` and multi-channel cases. Owner: Łukasz (Claude worker)
- [x] Real eval set `evals/cases.jsonl`: ≥ 30 cases, scenarios A–E, G, I, J at least twice, labelled sources. Owner:
  Michał. Branch `feat/eval-cases`: 41 cases in the mentor's question style, all five verdict classes; labels from
  Demagog ClaimReview ratings (fetched 2026-11-21) and official pages (NATO, MON, europa.eu); an independent label check
  ran and its findings are fixed. J cases fail until the fault switch below exists.
- [ ] Second eval set (#16, PR #23): 32 cases with ids `FC-*` appended to `evals/cases.jsonl`, 30 scored (A8 B6 C2 D4 E3 G4 I3), labels from Demagog, Konkret24, EUvsDisinfo. Owner: Łukasz (Claude worker). **Not done:** (1) the cache-corpus run is BLOCKED: no corpus exists yet, so committed results are no-corpus runs and do not count for submission; (2) FC-J01–FC-J02 are `skip`ped, not scored, until the fault switch below exists; (3) FC-I01–FC-I03 are EUvsDisinfo stand-ins, not the organiser's incident base (not available to us).
- [ ] Eval gaps to close once retrieval exists: C cases carry one Demagog rating each, not two credible sources
  disagreeing on the same measure; E cases put the injection in the submitted text, none in a fetched source page.
  Owner: ?
- [ ] Eval-only fault switch for scenario J (`simulate` in `evals/cases.jsonl`: `factcheck_api_unavailable`,
  `llm_unavailable`), passed by `evals/adapter.py` and honoured only for eval traffic. Owner: ?
- [x] Contract gaps for metrics (#15): `security_events` from two detectors, a fixed pattern pre-check in code and the extraction model's flag (events carry no wording; the pattern event and a "patterns only" limitation survive a failed model call) and `cost_usd` per answer (token usage priced by genai-prices through PydanticAI; 0.0 when no request was sent, null when unknown). Web and Discord show a notice when an event is logged. Not measured with a real key yet. Branch `LukiLenkiewicz/issue15-contract-metrics`. Owner: Łukasz (Claude worker)
- [x] Link input (#4): safe fetch (http/https, SSRF guard on every connection incl. redirects and DNS, ≤ 3 redirects, 10 s, 2 MB, HTML via trafilatura, PDF via pypdf), page URL kept in `CheckResult.page` for later evidence exclusion. Branch `LukiLenkiewicz/issue4-link-input`, stacked on #15, in review. Prompt injection found in a page is logged with `location="page"`. Owner: Łukasz (Claude worker). Open: page text cut to 5000 chars (same as pasted text, UNCONFIRMED choice); no eval case uses a URL yet.
- [ ] Privacy: mask obvious personal data, retention, deletable demo session. Owner: ?
- [ ] Deliverables: description ≤ 4000 chars, PDF ≤ 12 slides, video ≤ 3 min, cost estimate, risks. Owner: ?
- [ ] Optional after basics: moderator loop (scenario H), screenshots (F).
- [ ] Team OK on the web search provider (PROPOSED below, #7); then run ~20 Polish test queries once a key exists. Owner: Łukasz (Claude worker)

## Decisions

- 2026-11-21: Verdict rules (#10, `judge.decide`). A side counts when one `official`/`primary`/`fact_check` source or two independent origins back it with a verified quote. Origins: evidence sharing a publisher, the same quote or a named news agency (PAP, Reuters, ...) counts once. A publisher on both sides keeps the side the model marks as its own conclusion, else neither. Missing context counts only on a context/refute label with a `context_quote` (the words naming the other time, place, speaker or setting) found verbatim in the same document; a `gap` label (the data cannot settle the claim, quick case D01) only adds a limitation, and a publisher whose own conclusion is a gap counts for no side. Conflict (C): an allowlisted `news` agency's own finding (PAP, `own_conclusion`) counts as reliable against a reliable source, never alone, and its report of someone's words does not. Quotes match in the title or the fragment, never across their join. Quotes match with typography, case and spacing folded; digits, signs and separators exact. Both sides count: `brak wystarczających dowodów`, conflict shown (scenario C). Named missing context counts: `wprowadzające w błąd` (B). Else refute: `fałszywe`, support: `potwierdzone`, nothing: `brak wystarczających dowodów`. Sources older than `PRAWDOWID_ARCHIVE_DAYS` (730) get an archival warning. Thresholds are UNCONFIRMED guesses; corpus source-type labels are not fixed yet.
- 2026-11-21: Web search starts with **DuckDuckGo** through `ddgs` (backend `duckduckgo` only, no `auto` fallback to
  other engines), user decision; the Tavily proposal (#7) stays as the later replacement. DuckDuckGo has no official
  web search API (`ddgs` scrapes), which conflicts with the brief's rule on official APIs: needs a team OK before
  submission. The provider is one function (`SearchProvider` in `prawdowid/websearch.py`), so a Tavily wrapper is one
  new function. (#8)

- 2026-11-21: Verdicts are per claim. One extraction call returns ranked, self-contained claims with a source sentence and search queries; the top `PRAWDOWID_MAX_CHECKED_CLAIMS` (default 5) come in full (source sentence, reason, queries) and get a verdict; every other claim comes as one short sentence in `unchecked_claims`, no verdict. Reason: full detail for every claim timed out (45 s) on one long text in a manual run; UNCONFIRMED, no reproducible measurement in the repo yet. Values below 1 stop the service at startup. Queries per claim: `PRAWDOWID_QUERIES_PER_CLAIM` (default 3). Defaults are UNCONFIRMED guesses, not tuned. (#5)
- 2026-11-21: **PROPOSED, needs team OK** (#7). Web search for step 2b: **Tavily** `/search` as the provider, called
  with `include_domains` (allowlist, `include_domains_mode=restrict`) and `language="pl"` (a ranking boost, not a
  filter; `filter_by_language=True` makes it strict), through the official
  `tavily-python` SDK. Fallback on the same contract: **Exa** (`exa-py`, `includeDomains`, `userLocation="PL"`).
  Sources checked 2026-11-21. Reasons:
  - Official API, signup open, free tier of 1,000 credits a month without a card, which covers the demo and evals
    ([credits](https://docs.tavily.com/documentation/api-credits)).
  - Native domain allowlist, up to 300 domains, plus an ISO 639-1 `language` boost that becomes a strict filter
    with `filter_by_language=True`
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
- 2026-11-21: No database for now; each check is logged to stdout. Storage UNDECIDED. (`96f3b46`) Superseded by the
  Postgres decision below; the application still stores nothing.
- 2026-11-21: Frontend is static HTML/CSS/JS behind nginx, no build step; backend is JSON only. (`96f3b46`)
- 2026-11-21: Every push goes through `.githooks/pre-push` (ruff, pytest, eval, judge PASS). (`d5aa35b`)
- 2026-11-21 (Michał): Retrieval flow. Source domains are indexed ahead of time (fetch with trafilatura, store publication and
  retrieval dates), never scraped while a check runs. Per check, in parallel and each with its own timeout: the official
  corpus (BM25 + embeddings), Google Fact Check Tools API, the incident base (EUvsDisinfo + the organiser's base) and live
  official APIs (e.g. IMGW warnings). An incident match is context or secondary evidence, never a verdict. A link input is
  fetched and its address also goes to the incident base. Fallback web search only on an allowlist of trusted domains, one
  round, only if time is left; fetched pages are untrusted data. No evidence left: `brak wystarczających dowodów`.
  Diagram: board "Architektura" on https://claude.ai/artifact/3f8LsRGUNnpgVAhAEsZcgu (private until shared).
  Details and the rule for known disinformation domains (warning, never a verdict): `docs/adr/0001-evidence-retrieval-and-verdict.md`.
- 2026-11-21 (Michał): Brand. Logo is a question mark wearing a detective's deerstalker: red rounded square, white "?",
  navy hat. Vector files without font dependencies in `docs/brand/` (`znak.svg`, `znak-na-czerwonym.svg` for red
  backgrounds, `awatar.svg` for the Discord bot); `frontend/public/favicon.svg` uses `znak.svg`. Tagline: "Fakt ma
  przypis." We never claim to be "the source of truth": the brief rules out the role of an automatic judge of truth.
  Typeface: Figtree (SIL OFL), self-hosted in `frontend/public/fonts/` because the CSP allows no font hosts; the web
  hero and the pitch deck share the same look (giant title with an outlined echo, chat preview, verdict card).
- 2026-11-21: Public demo on one EU VPS (OVHcloud VPS-2, Limburg, Germany) with `docker compose` and Caddy
  (automatic HTTPS) in front of nginx. No Vercel. A push to `prod` deploys (GitHub Actions at first, replaced
  below); `prod` only takes commits already on `main`. DNS has only an A record: behind Docker's userland proxy all
  IPv6 visitors would share one rate-limit bucket. (`claude/deploy-config-43a484`)
- 2026-11-21 (Michał): no GitHub Actions, the account's Actions jobs are blocked by billing. The server fetches
  `prod` every minute (systemd timer, `deploy/pull-deploy.sh`) with a read-only deploy key and runs
  `docker compose up --build --wait`. (`claude/pull-deploy`)
- 2026-11-21: Database: Postgres 18 with pgvector 0.8.7 and pg_trgm as the `db` service next to the app on the VPS,
  no Supabase. Tables and corpus loading belong to the search work. (`claude/deploy-config-43a484`)

## Log (newest first, append only)

- 2026-11-21 Łukasz (Claude worker): merged the restacked #28 head (`4c596ff`, on `main` `ebfcf76`) into #10 `LukiLenkiewicz/issue10-judge` (PR #30): conflicts in `prawdowid/contract.py` (`SecurityEvent.location` keeps `source`, main's required `detector` kept; the judge's event now says `detector="model"`) and WORKLOG; gap stance, `context_quote` and scenario C rules untouched. Judge test now checks `detector="model"` (`d3c30d7`). Quick eval on `d3c30d7` (judge not wired into `verify()` yet): macro_f1 0.10, abstention 1.00, injection_resistance 0.00, end_to_end 0.89 (J01), median 3.4 s, cost $1.75/100.
- 2026-11-21 Łukasz (Claude worker): #10 PR #30 round 2 fixes: data gap gives no verdict (D01), missing context needs verified `context_quote` (paraphrase B variant), official vs PAP is a conflict (C), quotes never across title/body join, decomposed text keeps its own span.
- 2026-11-21 Łukasz (Claude worker): #10 PR #30 review fixes: fact-check debunk keeps its own conclusion, grounded missing context, syndicated copies one origin, exact numbers in quotes, `security_events` (location `source`) for injection in retrieved fragments.
- 2026-11-21 Łukasz (Claude worker): #10 `prawdowid/judge.py` steps 4 and 5, model labels with quotes, verdict rules in code, offline FunctionModel tests per rule. Branch `LukiLenkiewicz/issue10-judge`.
- 2026-11-21 Łukasz (Claude worker): merged `main` (`ebfcf76`) into #4 `LukiLenkiewicz/issue4-link-input` (PR #28): main's squashed #6–#15, UI and deploy kept; #4 link input re-applied on top; page checks screen patterns with `location="page"` too; security notice wording from main generalised to "W treści"; Discord page line uses main's `_field` escaping and URL limit; `uv.lock` re-locked (mcp + pypdf); a link that times out no longer claims pattern screening (only the URL was screened). Quick eval on `9993410` (9 cases, no corpus): macro_f1 0.10, abstention 1.00, injection_resistance 0.00, end_to_end 0.89 (J01 not simulated), median 3.8 s, cost $1.70/100.
- 2026-11-21 Łukasz (via Claude): #19 local Postgres source store ported from PR #34 onto `main` alone (`main`'s JSONL cache kept as is); live test against postgres:17 passes; database empty, seed blocked. Branch `feat/19-local-source-store`.
- 2026-11-21 Łukasz (via Claude): EUvsDisinfo lookup fixed against the live server (results wrapper, HTML stripped from fragments); branch `fix/euvsdisinfo-live-response`.
- 2026-11-21 Łukasz (via Claude): rebased #31 (PR #33) onto `main`: only its own changes (`prawdowid/euvsdisinfo.py`, tests, `mcp` extra); no longer stacked on #28 and #30.
- 2026-11-21 Łukasz (Claude worker): #31 PR #33 review fixes: a malformed link in a search hit skips that hit instead of raising; a bad key (401, JSON-RPC -32001) is not retried; offline test of the HTTP branch against a local 401 server.
- 2026-11-21 Łukasz (Claude worker): #31 `prawdowid/euvsdisinfo.py` EUvsDisinfo MCP `search` lookup (pydantic-ai MCP client), offline tests against an in-process FastMCP server. Branch `LukiLenkiewicz/issue31-euvsdisinfo`.
- 2026-11-21 Łukasz (via Claude): merged `main` (#26 squashed) into `LukiLenkiewicz/issue15-contract-metrics` (PR #27), retargeted PR #27 to `main`; security notices ported into the new web UI `render()` and the Discord `_field` notice.
- 2026-11-21 Łukasz (Claude worker): #15 review fixes on PR #27: pattern pre-check for injected instructions next to the model flag, event and limitation kept on failed checks, `cost_usd` and event count in the per-check log. Patterns are generic, but E01–E03 existed when they were written and all three hit them, so `injection_resistance` on those cases partly measures the patterns; new holdout E cases are needed for an honest number. No false positive on the other 28 cases. Branch `LukiLenkiewicz/issue15-contract-metrics`.
- 2026-11-21 Łukasz (Claude worker): #4 second review (PR #28): inline sign-in or subscribe walls and a password form beside a short preview return `cannot_check` with the paste-text message; worker concurrency test asserts peak live parsers instead of total started (deterministic); URLs with userinfo refused on every hop, secret query values and fragments redacted in logs, worker arguments and `page.url`.
- 2026-11-21 Łukasz (Claude worker): #4 review fixes (PR #28): redirects followed by hand with bodies never read, URL policy on every hop (trailing-dot social hosts too), extraction in a child process killed at the deadline (max 2 at once, PDF ≤ 50 pages, ≤ 20,000 chars, 20 MB per stream), title and publisher share the 5000-char budget.
- 2026-11-21 Łukasz (Claude worker): #4 link input: `prawdowid/link.py`, `CheckResult.page`, offline tests `tests/test_link.py`.
- 2026-11-21 Łukasz (Claude worker): #15 `security_events` and `cost_usd` in `CheckResult`, offline FunctionModel tests; quick eval without an API key now reports injection_resistance and cost_per_100_usd instead of unknown. Branch `LukiLenkiewicz/issue15-contract-metrics`.
- 2026-11-21 Łukasz (via Claude): merged `main` (#25 squashed) into `feat/8-web-search` (PR #26), retargeted PR #26 to `main`; WORKLOG conflicts resolved by keeping both sides.
- 2026-11-21 Łukasz (Claude worker): #8 review fixes (PR #26, Codex review): `prawdowid/safefetch.py` with DNS/IP SSRF guard, robots.txt per redirect hop and refusal on 429/5xx, capped robots and page bodies; cache keeps metadata only (no full text without a confirmed licence), 30-day retention, `delete_document`, latest fetch replaces the old one; PESEL masked next to a label. Branch `feat/8-web-search`.
- 2026-11-21 Łukasz (Claude worker): #8 web search (DuckDuckGo via `ddgs`), fetch, trafilatura extraction, JSONL source cache, `docs/sources.md`, offline tests. Corpus not built (DDG returns no results here). Branch `feat/8-web-search`.
- 2026-11-21 Łukasz (via Claude): merged `main` (#24 squashed) into `LukiLenkiewicz/issue9-rerank` (PR #25), retargeted PR #25 to `main`; WORKLOG conflicts resolved by keeping both sides.
- 2026-11-21 Łukasz (Claude worker): #9 PR #25 review fixes: Unicode/IDN URL exclusion, fetched text over title-only hits, exact dedupe keeps conflicting facts, input budget before splitting.
- 2026-11-21 Łukasz (Claude worker): #9 `prawdowid/rerank.py` dedupe and rerank of evidence per claim (Claude Haiku listwise, stdlib dedupe), offline FunctionModel tests. Branch `LukiLenkiewicz/issue9-rerank`.
- 2026-11-21 Łukasz (via Claude): merged `main` into `LukiLenkiewicz/issue13-discord` (PR #24); WORKLOG conflict resolved by keeping both sides.
- 2026-11-21 Michał (via Claude): merged #29, #20, #21 (WORKLOG conflicts resolved, judge PASS each) and #32 (deploy
  config); `prod` created at `8ff84db`. The Actions deploy job was not started (account billing), so `prod` was
  deployed by hand; new UI live on https://faktczyfejk.pl. `claude/pull-deploy`: deploy by pulling `prod` on the server.
  Actions leftovers removed: the `DEPLOY_*` variables, the `DEPLOY_SSH_KEY` secret and the CI key on the server.
- 2026-11-21 Łukasz (Claude worker): #13 Codex round 2 on PR #24: Discord no longer truncates; overflow and URLs longer than one message go to an `odpowiedz.md` attachment with every verdict and link; slash-callback test; a refused attachment ends with a notice. Merged `main` (stack base `feat/16-eval-set` is in `main`). Quick eval on `98983d6` with `PRAWDOWID_EXTRA_CHANNELS=discord`: channel_consistency 1.00, abstention 1.00, median 3.6 s, macro_f1 0.10, end_to_end 0.89. Still not run against a real Discord server.
- 2026-11-21 Łukasz (Claude worker): #13 Codex review on PR #24: Discord answers split only between lines (untrusted fields wrapped, then escaped, quotes reopened per line, long URLs on their own line or replaced, masked links broken), 75 s overall deadline on the API call.
- 2026-11-21 Łukasz (Claude worker): #13 merged `origin/feat/16-eval-set` (stack tip) into `LukiLenkiewicz/issue13-discord` (`59c3eaf`); Discord renders `kind`, `source_sentence` and `unchecked_claims` like the web form. Quick eval without an API key: every case `technical_error`, not committed.
- 2026-11-21 Łukasz (Claude worker): #13 Discord bot (discord.py 2.7.1) on the same API and `verify()`, offline formatter and web/Discord consistency tests, `make discord`, compose profile `discord`. Branch `LukiLenkiewicz/issue13-discord`.
- 2026-11-21 Michał: web answer in the organiser's format ("Tak." / "Nie." / "Nie udało mi się potwierdzić tej informacji." plus sources), the same text in copy-to-chat; example chips use the organiser's questions.
- 2026-11-21 Michał: web UI matched to the pitch deck: Figtree, flat red hero with the outlined title echo, labelled chat preview, verdict card with sources one per row and quotes on a red rule.
- 2026-11-21 Łukasz (Claude worker): merged `main` into `feat/16-eval-set` (PR #23); both eval sets kept, #16 cases renamed `FC-*` (73 cases). Quick eval on `69f1f82`: abstention 1.00, median 4.1 s, macro_f1 0.10, end_to_end 0.89.
- 2026-11-21 Łukasz (Claude worker): #16 Codex review fixes on PR #23: `skip` field in `evals/run.py` (J01–J02 skipped, not scored), single-assertion inputs for B05, B06, B02, G01, G03, G04, A05, E02, new A08, I01–I03 marked as stand-ins; corpus run marked blocked. Full no-corpus eval on `3ce9bae`: macro_f1 0.09, end_to_end 1.00.
- 2026-11-21 Łukasz (Claude worker): #16 `evals/cases.jsonl` with 31 labelled cases, full eval on `7ee1410` committed (macro_f1 0.09).
- 2026-11-21 Łukasz (Claude worker): #16 merged `feat/5-self-contained-claims` (stack), full eval rerun on `d655078`: macro_f1 0.09, median latency 5.0 s.
- 2026-11-21 Łukasz (Claude worker): merged `main` (#29 web UI) into `feat/5-self-contained-claims`; claim origin line and unchecked-claims list ported into the new UI. Quick eval on `6689ad6`: abstention 1.00, median 3.87 s, macro_f1 0.10, end_to_end 0.89 (no sources yet).
- 2026-11-21 Łukasz (Claude worker): #5 review fixes on PR #22: reject hyperparameters below 1, latency numbers marked UNCONFIRMED, quote test fixture uses only names from its input.
- 2026-11-21 Łukasz (Claude worker): #5 claims stand alone (pronouns, relative dates from the text), quotes split into attribution + quoted, queries per claim, top-N cap with `unchecked_claims`, source sentence shown in the UI. Branch `feat/5-self-contained-claims`.
- 2026-11-21 Michał (via Claude): deploy config on `claude/deploy-config-43a484` (`compose.prod.yaml`,
  `caddy/Caddyfile`, deploy workflow for `prod`, `docs/deploy.md`, README pointers). Compose files and the workflow
  pass their JSON schemas; reviewed. Bought OVHcloud VPS-2 and faktczyfejk.pl; DNS A records point at the server.
  Server: Docker 29.10, Compose 5.8, stack up with `--wait`; Let's Encrypt certificate, www redirect, 429 on the 11th
  check and a spoofed X-Forwarded-For ignored (checked over HTTPS); Postgres with vector 0.8.7 and pg_trgm 1.6,
  `pg_dump`/`pg_restore` tested.
- 2026-11-21 Michał: web UI accessibility pass from the `a11y-reviewer` and `web-design-guidelines` audits: focus kept during a check, no aria-busy, aria-invalid on errors, Enter sends only with a hardware keyboard, long URLs wrap, Polish source-type labels, chip hover contrast.
- 2026-11-21 Michał: UI tooling in `.claude/`: `web-design-guidelines` skill (Vercel Web Interface Guidelines, MIT, pinned copy) and `a11y-reviewer` agent (WCAG 2.2 AA, read-only); CLAUDE.md workflow row.
- 2026-11-21 Michał: pushed `feat/ui-frontend` (UI, ADR, brand, eval set) after a judge check; no eval rerun, the API code is unchanged and this clone has no model key.
- 2026-11-21 Michał: `feat/ui-frontend` merged `feat/eval-cases`; new web UI (`04d27db`): poster hero, detective logo, verdict card with sources before the model's assessment, honest "Wersja testowa" label until sources are connected.
- 2026-11-21 Michał: `feat/ui-frontend` ADR 0001 (retrieval and verdict flow, mentor's answer format), brand files in `docs/brand/`.
- 2026-11-21 Michał: `feat/eval-cases` real eval set, 41 cases A–J with sourced labels (Demagog ClaimReview, NATO, MON, europa.eu).
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
