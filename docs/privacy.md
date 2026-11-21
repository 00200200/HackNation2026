# Privacy

What we keep about a check, for how long, where text goes, and how to delete it (issue #17,
brief section 5).

## Masking

`prawdowid/privacy.py` (`mask_personal_data`) replaces with placeholders:

| Data | Rule | Placeholder |
|---|---|---|
| E-mail address | `name@domain.tld` | `[e-mail]` |
| Polish account number (NRB) | 26 digits, optional `PL`, groups of four | `[numer konta]` |
| Other IBAN | country code, check digits, mod-97 valid | `[numer konta]` |
| Phone number | `+48 600 100 200` or `600-100-200` | `[telefon]` |
| PESEL | 11 digits with a valid checksum | `[PESEL]` |
| Card number | 13–19 digits, in one run or groups of four, Luhn valid | `[numer karty]` |

It does not detect names, addresses or phone numbers written as `600 100 200` or `600100200`: in a
claim, digit runs like these are usually amounts. Checksums keep most ordinary numbers out (an
11-digit register number without a valid PESEL checksum stays).

We checked Presidio (presidio-analyzer 2.2.366, 2026-11-21). Its only Polish recognizer is PESEL,
which this module already covers, and it needs spaCy plus a language model. We kept the module.

Where masking runs:

| Call site | Masked? | Why |
|---|---|---|
| Text sent to Claude for claim extraction (`verifier.verify_text`), pasted text and the text of a linked page | yes | A placeholder keeps the sentence, so claims still split. A claim about the personal data itself (for example "this account belongs to the charity") can no longer be checked from the number, which is the point. The claim and source sentence shown to the user carry the placeholder. |
| Everything after extraction (`prawdowid/pipeline.py`, #11): web search, Google Fact Check, EUvsDisinfo, rerank, judge | yes, by construction | These steps take the claims and queries the model wrote from the masked text. Web search queries (`websearch.search_web`) and database queries (`cache.build_tsquery`) are masked again. |
| Check log record (`checklog.record`) | yes | The question, the claims, the unchecked claims and the source URLs are masked again when the record is written, so a call site that forgets to mask cannot leak into the log. |
| stdout log lines | yes | No raw user text: session id, channel, status, lengths, token counts, and the claims and search queries of each check (written by the model from the masked text, so a name or a phone written as `600 100 200` can still appear). Link URLs are masked (an e-mail in a query string), fetch errors are logged by type only. On top of that, every line of the `prawdowid` and `prawdowid.discord` loggers, tracebacks included, goes through `privacy.MaskingFilter` (set in `prawdowid/app.py` and `prawdowid/discord_bot.py`; uvicorn's own error log is not covered), so an unexpected exception that carries raw input is masked too. |
| The link itself, when it is fetched | no | We need the real address to fetch the page. |
| Evidence fragments from source pages | no | They are public pages, and the quote must match the page word for word. |

## What a check stores

One JSON line in the check log (`PRAWDOWID_CHECK_LOG`, default `logs/checks.jsonl`, in Docker
`/tmp/prawdowid/checks.jsonl` inside the backend container), written by `POST /api/checks` for
every check, also a failed or timed-out one (#14): session id, start and end time, total latency,
channel, the masked question, status, `error` (`"timeout"` when the API's 60 s limit fired, or the exception class when verify raised;
`null` when the pipeline returned a notice, also its own 25 s budget cut), the notice message, the masked page URL and content hash for a link, the
time of each step (`fetch`, `extract`, and per claim `factcheck`, `euvsdisinfo`, `web`, `rerank`,
`judge`, `retry_*`), every model answer (model name, input and output tokens), `cost_usd`, security
events (kind, location and detector, never the wording), ids of matched incidents, check-level
limitations, each claim with its
verdict, sources (masked URL and source type) and limitations (search errors, time limit), and the
claims left unchecked. Page text from a link is not stored. `GET /api/sessions/{id}` returns the
records of one session as stored. A check cut by the API's 60 s limit (the pipeline's own 25 s budget
normally ends it first), or one where verify raised, keeps its total latency, `error`, the notice
and the pattern-only screening: the steps and model calls it had made are lost with the cancelled
task.

Web search in a check also adds the public pages it fetched to the source cache
(`corpus/docs.jsonl`). Those carry no user text and no session id. A check never writes the
PostgreSQL source store (written only by the seed script; step 2c is off in the pipeline).

## Retention

One constant, `RETENTION_DAYS = 30` in `prawdowid/privacy.py`:

- Check log: records older than that are dropped when the next check is written (so with no new
  checks they stay until one comes). Damaged lines are dropped the same way.
- Source cache `corpus/docs.jsonl`: pages fetched more than that ago are dropped on the next save.
- Source store: each page gets `delete_after = now() + RETENTION_DAYS` on insert. Search and
  `stored_documents()` skip expired pages at once, but the rows are only deleted when
  `delete_expired_documents()` runs, and only the seed script runs it (before it writes). The seed
  script is the only writer, so expired pages stay in the database until the next seed. Before step
  2c is switched on, run it on a schedule (cron or `pg_cron`).
- Result cache (`prawdowid/app.py`, #59): the finished answer for a text is kept in the API
  process's memory for 30 minutes (at most 500 answers), under a hash of the normalised input, so
  the same text from the web form and from Discord gets the same answer. The answer holds the
  claims and the sentences they came from. It is never written to disk, a restart empties it, and
  "Usuń moje sprawdzenia" does not reach it (it expires on its own). A fast answer shows that the
  same text was checked in the last 30 minutes (response header `X-Cache: hit`), whoever sent it.
  This is not governed by `RETENTION_DAYS`.

Not covered: Docker's own stdout logs (rotation is set by the Docker host). They carry no raw user
text: claims, queries and link URLs, all from masked text.

## Demo session and deletion

The API gives every check a session id in the `X-Session-Id` response header. A client that sends
the header back keeps the same session. The web page keeps it in `sessionStorage` (until the tab
closes) and shows "Usuń moje sprawdzenia", which calls `DELETE /api/sessions/{id}` and removes every
check log record of that session. The answer is `{"deleted": <number of records>}`.
The session id is a bearer token: anyone who has it can read (`GET /api/sessions/{id}`) and
delete that session's records; there is no other login.

Discord sends no session id, so each Discord check gets its own session; deleting it takes an API
call with the id from the log.

## Where data is processed

| Service | What it receives | When |
|---|---|---|
| Anthropic API (Claude) | Masked text to check; claims and evidence fragments (rerank, judge) | Every check. |
| Google Fact Check Tools API | Claim text | Every checkable claim, when `GOOGLE_FACTCHECK_API_KEY` is set. |
| Tavily (`/search`, `tavily-python`) | Masked search queries | Every checkable claim, when `TAVILY_API_KEY` is set, and the corpus builder. |
| EUvsDisinfo MCP server (`mcp.euvsd.info`) | Claim text | Every checkable claim, when `EUVSDISINFO_API_KEY` is set. |
| The incident base (`prawdowid/incidents.py`) | The raw input and the final URL | Every check; local file, nothing leaves the server. |
| The site a link points to | A request from our server | Link checks. The site sees our server's address, not the user's. |

The region where each provider processes the data is UNCONFIRMED: we have not checked their data
residency terms for this demo.
