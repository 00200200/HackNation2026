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

## Decisions

- 2026-11-21: The model never decides truth. It extracts claims; verdicts are set in code from evidence. (`b52c248`)
- 2026-11-21: Model through PydanticAI, default `anthropic:claude-opus-5-5`, swappable with `PRAWDOWID_MODEL`. (`b52c248`)
- 2026-11-21: No database for now; each check is logged to stdout. Storage UNDECIDED. (`96f3b46`)
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

## Log (newest first, append only)

- 2026-11-21 Michał: `feat/ui-frontend` ADR 0001 (retrieval and verdict flow, mentor's answer format), brand files in `docs/brand/`.
- 2026-11-21 Łukasz: linked the architecture board in README, committed the quick eval on `c27b642`, pushed `feat/llm-verifier`.
- 2026-11-21 Łukasz: added this worklog and the CLAUDE.md rule to keep it current.
- 2026-11-21 Łukasz: `c27b642` prompt keeps injected instructions out of claims, checks yes/no questions.
- 2026-11-21 Łukasz: `b52c248` PydanticAI agent as the verifier, offline tests with FunctionModel. Quick eval run.
- 2026-11-21 Michał: `d5aa35b` pre-push gate, `judge` agent, jury rules, eval harness (`evals/`).
- 2026-11-21 Łukasz: `96f3b46` (#1) service skeleton: contract, stub verifier, nginx frontend, Docker, Makefile.
- 2026-11-21 Michał: `db1f374` Claude Code setup (skills, agents, settings) and uv project.
