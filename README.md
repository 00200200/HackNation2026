# PRAWDOWID

You paste a text or a link and get back, for each claim in it, a verdict and the sources behind
it, written in plain Polish. This repository holds the service around the verification pipeline:
the shared contract, the web page, the HTTP API and the check log.

**Status:** the verifier is a stub. Every check returns `cannot_check` with the notice
"Weryfikacja nie jest jeszcze podłączona…". The service never produces a verdict or a source yet.

## Run

```bash
uv run uvicorn prawdowid.app:app
```

Open http://127.0.0.1:8000. The API docs are at http://127.0.0.1:8000/docs.

The check log is SQLite. Its path comes from `PRAWDOWID_DB_PATH` and defaults to
`data/checks.sqlite3` in the repository root. That `data/` directory is git-ignored.

## API

| Method and path | What it does |
|---|---|
| `POST /api/checks` | Body `{"input": "...", "session_id": "..."}` (`session_id` is optional). Runs the check (60 s timeout), stores it, returns `{"id", "result"}`. Limited to 10 requests per minute per client IP. |
| `GET /api/checks/{id}` | One stored check. |
| `GET /api/checks` | All stored checks, newest first, for audit and export. |
| `DELETE /api/sessions/{session_id}` | Deletes every check of that session. |
| `GET /health` | Liveness. |
| `GET /`, `POST /` | The web page and its form. |

Input is trimmed and must be 1 to 5000 characters. A single token containing `://` counts as a
link and must be a valid `http` or `https` URL. Links are not fetched yet.

The web page puts each browser in its own session (a cookie) and shows the session id in the
footer. To remove a demo session:

```bash
curl -X DELETE http://127.0.0.1:8000/api/sessions/<session-id>
```

**Demo only, no authentication.** Anyone who can reach the service can list every stored check
and delete any session. Session ids are not secrets. Do not enter personal data.

## Layout

- `prawdowid/contract.py`: `Verdict`, `Status`, `Source`, `ClaimResult`, `CheckResult`.
- `prawdowid/verifier.py`: `async def verify(text) -> CheckResult`, the one function every
  channel calls.
- `prawdowid/checklog.py`: the `checks` table. Columns for model name, tokens, cost, abstention
  and security events already exist and stay empty until the pipeline fills them.
- `prawdowid/app.py`: API, web channel, rate limit. Turns an exception in `verify` into
  `technical_error`.

## Checks

```bash
uv run pytest
```

```bash
uv run ruff format . && uv run ruff check .
```
