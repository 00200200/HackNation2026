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
| Check log record (`checklog.record`) | yes | The question is stored masked. |
| stdout log lines | yes | They carry no user text: session id, channel, status, lengths, token counts. Link URLs are masked (an e-mail in a query string), fetch errors are logged by type only. |
| The link itself, when it is fetched | no | We need the real address to fetch the page. |
| Evidence fragments from source pages | no | They are public pages, and the quote must match the page word for word. |

## What a check stores

One JSON line in the check log (`PRAWDOWID_CHECK_LOG`, default `logs/checks.jsonl`, in Docker
`/tmp/prawdowid/checks.jsonl` inside the backend container): session id, time, channel, the masked
question, status, each claim with its verdict and source URLs, and the claims left unchecked. Page
text from a link is not stored.

Web search in a check also adds the public pages it fetched to the source cache
(`corpus/docs.jsonl`). Those carry no user text and no session id. A check never writes the
PostgreSQL source store (written only by the seed script; step 2c is off in the pipeline).

## Retention

One constant, `RETENTION_DAYS = 30` in `prawdowid/privacy.py`:

- Check log: records older than that are dropped when the next check is written (so with no new
  checks they stay until one comes). Damaged lines are dropped the same way.
- Source cache `corpus/docs.jsonl`: pages fetched more than that ago are dropped on the next save.
- Source store: each page gets `delete_after = now() + RETENTION_DAYS` on insert;
  `delete_expired_documents()` removes expired pages and the seed script runs it first.

Not covered: Docker's own stdout logs (rotation is set by the Docker host). They carry no raw user
text: link checks log the masked URL and the claims, which come from the masked text.

## Demo session and deletion

The API gives every check a session id in the `X-Session-Id` response header. A client that sends
the header back keeps the same session. The web page keeps it in `sessionStorage` (until the tab
closes) and shows "Usuń moje sprawdzenia", which calls `DELETE /api/sessions/{id}` and removes every
check log record of that session. The answer is `{"deleted": <number of records>}`.

Discord sends no session id, so each Discord check gets its own session; deleting it takes an API
call with the id from the log.

## Where data is processed

| Service | What it receives | When |
|---|---|---|
| Anthropic API (Claude) | Masked text to check; claims and evidence fragments (rerank, judge) | Every check. |
| Google Fact Check Tools API | Claim text | Every checkable claim, when `GOOGLE_FACTCHECK_API_KEY` is set. |
| DuckDuckGo (through `ddgs`) | Masked search queries | Every checkable claim, and the corpus builder. |
| EUvsDisinfo MCP server (`mcp.euvsd.info`) | Claim text | Every checkable claim, when `EUVSDISINFO_API_KEY` is set. |
| The incident base (`prawdowid/incidents.py`) | The raw input and the final URL | Every check; local file, nothing leaves the server. |
| The site a link points to | A request from our server | Link checks. The site sees our server's address, not the user's. |

The region where each provider processes the data is UNCONFIRMED: we have not checked their data
residency terms for this demo.
