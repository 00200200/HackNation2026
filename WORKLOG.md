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
`nie podlega weryfikacji`. Links return `cannot_check`. Nothing is stored.

**Branches**

| Branch | State |
|---|---|
| `main` / `origin/main` | at `7ee1410`: skeleton (#1), pre-push gate, PydanticAI verifier (#2), worklog and eval results (#3). |
| `feat/7-search-provider` | #7 search provider research, WORKLOG only. PR open, not merged. Owner: Łukasz (Claude worker). |
| `feat/8-web-search` | #8 web search (DuckDuckGo via `ddgs`), page fetch, source cache, `docs/sources.md`. Stacked on `LukiLenkiewicz/issue9-rerank`, PR open, not merged. Corpus not built. Owner: Łukasz (Claude worker). |
| `feat/16-eval-set` | #16 eval set (31 cases) and full eval, stacked on `feat/5-self-contained-claims`. PR open, not merged. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue12-incidents` | #12 scenario I incident matcher, empty base. Stacked on `feat/8-web-search` (or the stack tip at push), PR open, not merged. Owner: Łukasz (Claude worker). |
| `LukiLenkiewicz/issue9-rerank` | #9 step 3 rerank and dedupe, stacked on `LukiLenkiewicz/issue13-discord` (PR #24). PR open, not merged. Owner: Łukasz (Claude worker). |
| `origin/feat/service-skeleton`, `origin/tooling/judge-eval-gate` | already in `main` (squashed). Safe to delete after a team OK. |

**Last eval** (`evals/results/latest.json`, **full**, 31 real cases from `evals/cases.jsonl`, product at `d655078` (#5 merged into #16), no corpus):
macro_f1 0.09 (fail, target ≥ 0.75), abstention 1.00, injection_resistance 0.00 (fail: no `security_events`, verdicts
wrong), median latency 5.0 s, end_to_end 0.94 (fail: both J cases, no eval switch to simulate a failure). Citation metrics,
channel consistency and cost: not measured (no corpus, no second channel, no `cost_usd`). Every checkable case returns
`brak wystarczających dowodów`: expected while there are no sources.

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
  - [x] Step 3 (#9): `prawdowid/rerank.py`, per claim: drops the linked page (`exclude_url`) and repeated canonical URLs, splits page text into fragments of ≤ `PRAWDOWID_FRAGMENT_CHARS` (800), drops near-duplicates (word-trigram Jaccard ≥ 0.8), interleaves documents and sends at most `PRAWDOWID_RERANK_MAX_FRAGMENTS` (60), Claude Haiku via PydanticAI orders them, top `PRAWDOWID_RERANK_TOP_K` (12) kept with `doc_id` = canonical URL. Model failure or no key: unranked order plus a limitation. Not wired into `verify()` (#11). Ranking quality not measured, no key yet. Owner: Łukasz (Claude worker)
- [x] Second channel (#13): Discord `/sprawdz` bot, `prawdowid/discord_bot.py`, calls the same `POST /api/checks` with `X-Channel: discord`, branch `LukiLenkiewicz/issue13-discord`. Not run against real Discord (token not used by the worker); eval `channel_consistency` needs `PRAWDOWID_EXTRA_CHANNELS=discord` and multi-channel cases. Owner: Łukasz (Claude worker)
- [x] Real eval set `evals/cases.jsonl`: 31 cases, scenarios A–E, G, I, J at least twice, labels from Demagog, Konkret24, EUvsDisinfo. Owner: Łukasz (Claude worker). Open: I cases use EUvsDisinfo, not the organiser's incident base (not available to us); EUvsDisinfo blocks automated fetch, so check I01–I03 labels by hand; J cases need a product eval switch to simulate a missing key or limit.
- [x] Scenario I (#12): `prawdowid/incidents.py` matches the input against the incident base on URL (canonical), flagged domain and text similarity (difflib, per sentence, ≥ `PRAWDOWID_INCIDENT_MIN_SIMILARITY` 0.7, a guess), result in `CheckResult.incident_matches`, added in `app.py` after `verify()` so it never touches a verdict; web form and Discord show it as a neutral note. Base path `PRAWDOWID_INCIDENTS_PATH`, default `prawdowid/data/incidents.json`, shipped **empty**: the organiser's file is not here yet, so nothing matches and the I eval cases show no warning. File format (JSON list or CSV: `id`, `text`, optional `url`, `domain`) is UNCONFIRMED. Owner: Łukasz (Claude worker), branch `LukiLenkiewicz/issue12-incidents`. Open: load the organiser's file when it arrives, check its fields (a `url` without a scheme never matches), tune the threshold and measure difflib latency on it.
- [ ] Contract gaps for metrics: `security_events`, `cost_usd` per answer. Owner: ?
- [ ] Link input (fetch page, treat it as untrusted source text). Owner: ?
- [ ] Privacy: mask obvious personal data, retention, deletable demo session. Owner: ?
- [ ] Deliverables: description ≤ 4000 chars, PDF ≤ 12 slides, video ≤ 3 min, cost estimate, risks. Owner: ?
- [ ] Optional after basics: moderator loop (scenario H), screenshots (F).
- [ ] Team OK on the web search provider (PROPOSED below, #7); then run ~20 Polish test queries once a key exists. Owner: Łukasz (Claude worker)

## Decisions

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

- 2026-11-21 Łukasz (Claude worker): #12 incident matcher (URL, domain, difflib text similarity) with an empty shipped base, `incident_matches` in the contract, rendered on web and Discord, offline tests with a test-only fixture. Branch `LukiLenkiewicz/issue12-incidents`.
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
