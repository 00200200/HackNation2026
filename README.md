# PRAWDOWID

You paste a text or a link and get back, for each claim in it, a verdict and the sources behind
it, written in plain Polish. This repository holds the service around the verification pipeline:
the shared contract, the HTTP API and the web frontend.

**Status:** the verifier sends the text to Claude (through PydanticAI) and gets back a list of
claims, each marked checkable or not. The model never decides whether a claim is true. Each
checkable claim then goes through `prawdowid/pipeline.py` in parallel with the others: Google Fact
Check, EUvsDisinfo known narratives (context only, never a verdict on its own) and web search on
allowlisted domains (our own database, #19, is out of the pipeline for now), then
rerank and a judge that labels quotes; the verdict is set in code (`judge.decide`). The whole check
has one time budget (`PRAWDOWID_CHECK_BUDGET_S`, 25 s). A claim that runs out of time, or whose
web search, Fact Check and EUvsDisinfo all fail, comes back `not_checked` with the reason, never as a verdict. An
opinion, forecast or question is `not_verifiable`. A link is fetched (`prawdowid/link.py`) and the page's
main text is checked like pasted text; a blocked page, paywall, login wall, social media post,
private address or file that is not HTML or PDF comes back as `cannot_check` with a request to
paste the text. Nothing is stored; each check is logged to stdout (status, latency, input length)
with a second line for the model call (model, input and output tokens, latency).

## Configuration

Put these in `.env` in the repository root. The file is git-ignored and is not copied into the
image; `docker compose` and `make dev` read it at start-up.

| Variable | Required | Default | What it does |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | none | Anthropic API key. Without it every check returns `technical_error`. |
| `PRAWDOWID_MODEL` | no | `anthropic:claude-opus-5-5` | PydanticAI model id (`provider:model`). |
| `PRAWDOWID_CHECK_BUDGET_S` | no | `25` | Time budget for the whole check, in seconds. Claims still running at the end are `not_checked`. |
| `PRAWDOWID_WEB_SEARCH_BUDGET_S` | no | `10` | Longest one web search query may take, retry included, before it counts as unavailable. |
| `PRAWDOWID_PAGE_BUDGET_S` | no | `8` | Longest one page fetch may take (robots.txt and page); a slower page is skipped, the others are kept. |
| `PRAWDOWID_RETRY_MIN_S` | no | `18` | A claim without enough evidence is searched once more only if at least this many seconds remain. |
| `DISCORD_BOT_TOKEN` | only for the Discord bot | none | Bot token from the Discord developer portal. Without it the bot refuses to start. |
| `PRAWDOWID_API_URL` | no | `http://127.0.0.1:8000` | API the Discord bot calls (`http://backend:8000` in Docker). |
| `GOOGLE_FACTCHECK_API_KEY` | no | none | Google API key with the Fact Check Tools API enabled. Without it the known-claim lookup is skipped and reported as unavailable. |
| `DATABASE_URL` | no | none | Postgres URI of the step 2c source store, used only by the seed script (`make db-seed` sets it) and `cache.search_documents`. Step 2c is disabled in the pipeline until licensed sources are chosen, so checks never read or write the database and the backend runs without it. Start the database with `make db` (127.0.0.1:5433). |
| `POSTGRES_PASSWORD` | no | `prawdowid` | Password of the local `db` service (port bound to 127.0.0.1 only). Applies only when the volume is created (`docker compose --profile db down -v` to recreate). The database starts empty: seed it with `make db-seed`. |
| `EUVSDISINFO_API_KEY` | no | none | Personal API key for the EUvsDisinfo MCP server (`https://mcp.euvsd.info/mcp`), generated on euvsdisinfo.eu. Sent as the `X-API-Key` header. Without it the EUvsDisinfo lookup is skipped and reported as unavailable. |

The model call has a 45 s deadline and at most one retry, inside the API's 60 s limit. Provider
errors, rate limits, timeouts and a missing key return `technical_error`; a model refusal returns
`cannot_check`. Both carry a Polish message and no claims.

## Run

Needs Docker with Compose.

```bash
make up
```

Open http://localhost:8080. Stop with `make down`. Use another port with `make up PORT=9000`.

Without `make`: `docker compose up --build -d`.

Run `make help` to list every target. The ones used most:

| Target | What it does |
|---|---|
| `make up` / `make down` / `make logs` | Docker stack: frontend on `PORT` (default 8080), backend internal only |
| `make dev` | API alone on http://127.0.0.1:8000 with reload (docs at `/docs`) |
| `make discord` | Discord bot against `make dev`; `make up DISCORD=1` runs it in Docker |
| `make check` | `ruff format --check`, `ruff check`, `pytest` |
| `make format` | Format and autofix |

## Architecture board

The team's architecture whiteboard: https://claude.ai/artifact/W9KUaX37YHjRFjAzZedyvs

## Layout

- `frontend/`: static `index.html`, `styles.css` and `app.js` (no build step) served by nginx.
  nginx also proxies `/api/` and `/health` to the backend, caps request bodies at 64 KB and sets
  a strict Content-Security-Policy.
- `Dockerfile`: the backend image (Python 3.13, uv, runs as `nobody`).
- `compose.yaml`: both services. Only the frontend port is published.
- `prawdowid/contract.py`: `Verdict`, `Status`, `Source`, `ClaimResult`, `CheckResult` (with `page`,
  `security_events`, `cost_usd`).
- `prawdowid/link.py`: `fetch_page(url)`, the guarded fetch and text extraction for link input.
- `prawdowid/verifier.py`: `async def verify(text) -> CheckResult`, the one function every
  channel calls. Holds the PydanticAI agent, its prompt and `to_check_result`, the pure function
  that turns the model's claims into verdicts.
- `prawdowid/factcheck.py`: `search_claims(claim)`, the known-claim lookup in Google Fact Check
  Tools (`claims:search`). Each review becomes a `Source` (`source_type="fact_check"`) with the
  fact-checker's rating and the reviewed claim kept beside it, not in `fragment`: the rating is a
  signal, not a verdict. One retry on a network error or 5xx, 15 s deadline for the whole lookup. A missing key, 4xx (bad key, quota) or outage returns a `limitation`
  message and no hits. Not wired into `verify()` yet (issue #11).
- `prawdowid/app.py`: the API, input validation, rate limit, and the `technical_error` path.
- `prawdowid/discord_bot.py`: the second channel, a `/sprawdz tekst:` slash command (discord.py).
  It sends the same `POST /api/checks` as the web form, with `X-Channel: discord`, and renders the
  `CheckResult` with the same sections (verdict, reasoning, strength, premises, sources with
  quotes, limitations). User and source text is escaped and messages never ping anyone. Long
  answers are split into at most 5 messages of 2000 characters; API errors are shown as notices.
  The bot shares one API rate limit (10 per minute) for all its users.

## API

| Method and path | What it does |
|---|---|
| `POST /api/checks` | Body `{"input": "..."}`. Returns `CheckResult`. 60 s timeout on `verify`; 10 requests per minute per client IP. |
| `GET /health` | Liveness. |

Input is trimmed and must be 1 to 5000 characters. A single token containing `://` counts as a
link and must be a valid `http` or `https` URL. The page is fetched only from public addresses
(checked on every connection, so redirects and DNS cannot reach private, loopback or link-local
hosts), with at most 3 redirects, a 10 s deadline and a 2 MB cap; HTML goes through trafilatura,
PDF through pypdf, and the first 5000 characters go to the verifier. `CheckResult.page` carries the
page URL, content hash, title, publisher and date, never the page text. Validation errors come
back as 422 with a Polish message in `detail[0].msg`.

`ClaimResult` carries `verdict_label`, the Polish label for its verdict, so channels do not keep
their own copy of the labels.

## Pre-push gate

Run once per clone:

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-push` refuses a push without a `judge` agent PASS for the pushed commit, and on secrets, tracked
`.env` files, files over 10 MB, or failing ruff or pytest. Once an eval has run in the clone, product changes also
need a clean eval run on the pushed commit (`uv run python -m evals.run --quick`). The submission push is
`HN_FINAL=1 git push`. Rules: `.claude/skills/hacknation-judging/SKILL.md` and `.claude/skills/prawdowid-eval/SKILL.md`.
