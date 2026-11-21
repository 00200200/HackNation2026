# PRAWDOWID

You paste a text or a link and get back, for each claim in it, a verdict and the sources behind
it, written in plain Polish. This repository holds the service around the verification pipeline:
the shared contract, the HTTP API and the web frontend.

**Status:** the verifier sends the text to Claude (through PydanticAI) and gets back a list of
claims, each marked checkable or not. The model never decides whether a claim is true. There are
no sources yet, so the verdict is set in code: a checkable claim is always `insufficient_evidence`
with a note that the source base is not connected, and an opinion, forecast or question is
`not_verifiable`. `sources` is always empty. Links are not supported yet and come back as
`cannot_check`. Nothing is stored; each check is logged to stdout (status, latency, input length)
with a second line for the model call (model, input and output tokens, latency).

## Configuration

Put these in `.env` in the repository root. The file is git-ignored and is not copied into the
image; `docker compose` and `make dev` read it at start-up.

| Variable | Required | Default | What it does |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | none | Anthropic API key. Without it every check returns `technical_error`. |
| `PRAWDOWID_MODEL` | no | `anthropic:claude-opus-5-5` | PydanticAI model id (`provider:model`). |
| `GOOGLE_FACTCHECK_API_KEY` | no | none | Google API key with the Fact Check Tools API enabled. Without it the known-claim lookup is skipped and reported as unavailable. |
| `DOMAIN` | with `compose.prod.yaml` | none | Public domain Caddy gets the HTTPS certificate for (`compose.prod.yaml`, see `docs/deploy.md`). |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | with `compose.prod.yaml` | none | Database, user and password of the `db` service. `compose.prod.yaml` passes them to the backend as `DATABASE_URL`. |

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

Public deployment with HTTPS on a server: [docs/deploy.md](docs/deploy.md).

Run `make help` to list every target. The ones used most:

| Target | What it does |
|---|---|
| `make up` / `make down` / `make logs` | Docker stack: frontend on `PORT` (default 8080), backend internal only |
| `make dev` | API alone on http://127.0.0.1:8000 with reload (docs at `/docs`) |
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
- `compose.prod.yaml`, `caddy/Caddyfile`: production overlay. Caddy serves HTTPS in front of nginx
  and is then the only service with published ports; `db` is Postgres 18 with pgvector and pg_trgm.
- `.github/workflows/deploy.yml`: a push to the `prod` branch deploys to the demo server; setup in
  `docs/deploy.md`.
- `prawdowid/contract.py`: `Verdict`, `Status`, `Source`, `ClaimResult`, `CheckResult`.
- `prawdowid/verifier.py`: `async def verify(text) -> CheckResult`, the one function every
  channel calls. Holds the PydanticAI agent, its prompt and `to_check_result`, the pure function
  that turns the model's claims into verdicts.
- `prawdowid/factcheck.py`: `search_claims(claim)`, the known-claim lookup in Google Fact Check
  Tools (`claims:search`). Each review becomes a `Source` (`source_type="fact_check"`) with the
  fact-checker's rating and the reviewed claim kept beside it, not in `fragment`: the rating is a
  signal, not a verdict. One retry on a network error or 5xx, 15 s deadline for the whole lookup. A missing key, 4xx (bad key, quota) or outage returns a `limitation`
  message and no hits. Not wired into `verify()` yet (issue #11).
- `prawdowid/app.py`: the API, input validation, rate limit, and the `technical_error` path.

## API

| Method and path | What it does |
|---|---|
| `POST /api/checks` | Body `{"input": "..."}`. Returns `CheckResult`. 60 s timeout on `verify`; 10 requests per minute per client IP. |
| `GET /health` | Liveness. |

Input is trimmed and must be 1 to 5000 characters. A single token containing `://` counts as a
link and must be a valid `http` or `https` URL. Links are not fetched yet: a valid link returns
`cannot_check`. Validation errors come
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
