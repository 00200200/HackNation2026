# Worklog

Shared state of the project for people and agents. Read it before starting work; update it when you
finish a task, open or merge a branch, or change a decision. Keep "Now" and "Next" true; append to
"Log" (newest first). Facts only: link commits, branches and eval runs; mark guesses UNCONFIRMED.

Challenge: Prawdowid (MSZ) at HackNation 2026. Submission closes **22.11.2026 11:00**.
Rules and jury criteria: `.claude/skills/hacknation-judging/SKILL.md`. Metrics: `.claude/skills/prawdowid-eval/SKILL.md`.

## Now (snapshot, edit in place)

Updated: 2026-11-21 13:30, by Łukasz (via Claude).

**Works end to end:** web form (nginx, `frontend/`) → `POST /api/checks` (FastAPI, `prawdowid/app.py`) →
`verify()` (`prawdowid/verifier.py`) → PydanticAI agent on Claude splits the text into claims marked checkable or
not → verdict set in code. No sources yet, so every checkable claim is `brak wystarczających dowodów` and the rest
`nie podlega weryfikacji`. Links return `cannot_check`. Nothing is stored.

**Branches**

| Branch | State |
|---|---|
| `main` / `origin/main` | at `d5aa35b` (pre-push gate). Local `main` is behind: `git pull` before branching. |
| `feat/llm-verifier` | PydanticAI verifier (`b52c248`), prompt tweaks (`c27b642`), worklog, eval results. Pushed to `origin/feat/llm-verifier`, not merged into `main`. |
| `feat/7-search-provider` | #7 search provider research, WORKLOG only. PR open, not merged. Owner: Łukasz (Claude worker). |
| `origin/feat/service-skeleton`, `origin/tooling/judge-eval-gate` | already in `main` (squashed). Safe to delete after a team OK. |

**Last eval** (`evals/results/latest.json`, quick, 4 example cases, commit `c27b642`, does not count for submission):
macro_f1 0.33 (fail, target ≥ 0.75), abstention 1.00, injection_resistance 0.00 (fail), median latency 2.6 s,
end_to_end 1.00, moderator_loop 0.00. Citation metrics, channel consistency and cost: not measured.
Every case returns `brak wystarczających dowodów`: expected while there are no sources.

**Architecture board:** https://claude.ai/artifact/W9KUaX37YHjRFjAzZedyvs (also linked from README).

## Next (open work, take one and put your name on it)

Basic requirements first: the jury gives no points for extras if one of these is missing.

- [ ] Merge `feat/llm-verifier` into `main` (pushed, needs a PR and a team OK). Owner: Łukasz
- [ ] Demo corpus: ≥ 100 documents, ≥ 10 domains, ≥ 2 source types, publication and retrieval dates. Owner: ?
- [ ] Retrieval and evidence: sources with title, publisher, date, URL, quote; verdicts beyond "no evidence". Owner: ?
- [ ] Second channel (Discord or other allowed one; not Telegram/WeChat) on the same `verify()`. Owner: ?
- [ ] Real eval set `evals/cases.jsonl`: ≥ 30 cases, scenarios A–E, G, I, J at least twice, labelled sources. Owner: ?
- [ ] Contract gaps for metrics: `security_events`, `cost_usd` per answer. Owner: ?
- [ ] Link input (fetch page, treat it as untrusted source text). Owner: ?
- [ ] Privacy: mask obvious personal data, retention, deletable demo session. Owner: ?
- [ ] Deliverables: description ≤ 4000 chars, PDF ≤ 12 slides, video ≤ 3 min, cost estimate, risks. Owner: ?
- [ ] Optional after basics: moderator loop (scenario H), screenshots (F).
- [ ] Team OK on the web search provider (PROPOSED below, #7); then run ~20 Polish test queries once a key exists. Owner: Łukasz (Claude worker)

## Decisions

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
- 2026-11-21: No database for now; each check is logged to stdout. Storage UNDECIDED. (`96f3b46`)
- 2026-11-21: Frontend is static HTML/CSS/JS behind nginx, no build step; backend is JSON only. (`96f3b46`)
- 2026-11-21: Every push goes through `.githooks/pre-push` (ruff, pytest, eval, judge PASS). (`d5aa35b`)

## Log (newest first, append only)

- 2026-11-21 Łukasz (Claude worker): #7 search provider research; Tavily PROPOSED in Decisions, needs team OK. Branch `feat/7-search-provider`.
- 2026-11-21 Łukasz: linked the architecture board in README, committed the quick eval on `c27b642`, pushed `feat/llm-verifier`.
- 2026-11-21 Łukasz: added this worklog and the CLAUDE.md rule to keep it current.
- 2026-11-21 Łukasz: `c27b642` prompt keeps injected instructions out of claims, checks yes/no questions.
- 2026-11-21 Łukasz: `b52c248` PydanticAI agent as the verifier, offline tests with FunctionModel. Quick eval run.
- 2026-11-21 Michał: `d5aa35b` pre-push gate, `judge` agent, jury rules, eval harness (`evals/`).
- 2026-11-21 Łukasz: `96f3b46` (#1) service skeleton: contract, stub verifier, nginx frontend, Docker, Makefile.
- 2026-11-21 Michał: `db1f374` Claude Code setup (skills, agents, settings) and uv project.
