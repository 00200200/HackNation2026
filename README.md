# PRAWDOWID

You paste a text or a link and get back, for each claim in it, a verdict and the sources behind
it, written in plain Polish. This repository holds the service around the verification pipeline:
the shared contract, the HTTP API and the web frontend.

**Status:** the verifier is a stub. Every check returns `cannot_check` with the notice
"Weryfikacja nie jest jeszcze podłączona…". The service never produces a verdict or a source yet.
Nothing is stored; each check is only logged to stdout (status, latency, input length).

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
| `make check` | `ruff format --check`, `ruff check`, `pytest` |
| `make format` | Format and autofix |

## Layout

- `frontend/`: static `index.html`, `styles.css` and `app.js` (no build step) served by nginx.
  nginx also proxies `/api/` and `/health` to the backend, caps request bodies at 64 KB and sets
  a strict Content-Security-Policy.
- `Dockerfile`: the backend image (Python 3.13, uv, runs as `nobody`).
- `compose.yaml`: both services. Only the frontend port is published.
- `prawdowid/contract.py`: `Verdict`, `Status`, `Source`, `ClaimResult`, `CheckResult`.
- `prawdowid/verifier.py`: `async def verify(text) -> CheckResult`, the one function every
  channel calls.
- `prawdowid/app.py`: the API, input validation, rate limit, and the `technical_error` path.

## API

| Method and path | What it does |
|---|---|
| `POST /api/checks` | Body `{"input": "..."}`. Returns `CheckResult`. 60 s timeout on `verify`; 10 requests per minute per client IP. |
| `GET /health` | Liveness. |

Input is trimmed and must be 1 to 5000 characters. A single token containing `://` counts as a
link and must be a valid `http` or `https` URL. Links are not fetched yet. Validation errors come
back as 422 with a Polish message in `detail[0].msg`.

`ClaimResult` carries `verdict_label`, the Polish label for its verdict, so channels do not keep
their own copy of the labels.
