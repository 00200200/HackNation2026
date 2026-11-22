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
| Phone number | With a country code (`+48 600 100 200`, `(+48) 600 123 456`, `+48600123456`, `0048 …`, `(48) …`): any nine digits, grouped 3-3-3, 3-2-2-2 or 2-3-2-2 (a landline: `+48 22 123 45 67`) or in one run. Without one: `600-100-200`, a landline with its area code in brackets (`(22) 123 45 67`), or nine digits (`600 100 200`, `600100200`, `600 12 34 56`) that start with a mobile prefix or follow a label such as "tel." (`tel. nr 22 123 45 67`) | `[telefon]` |
| PESEL | 11 digits with a valid checksum | `[PESEL]` |
| ID card number | 3 capital letters and 6 digits, with or without a space (`ABC123456`, `ABC 123456`), check digit valid | `[numer dowodu]` |
| Passport number | 2 capital letters and 7 digits, no space (`AB1234567`) | `[numer paszportu]` |
| Card number | 13–19 digits, in one run or groups of four, Luhn valid | `[numer karty]` |

It does not detect names or addresses. Names of public figures stay on purpose: the mentor's guidance
(Discord, 21.11) is to mask PESEL, ID card and phone numbers, but not what changes the meaning of the
question or is needed to find evidence. For the same reason ordinary numbers stay:

- Amounts, years and statute references (`123456789 zł`, `500 000 000 zł`, `w 2024 roku 1500 osób`,
  `Dz.U. 2024 poz. 123`). A bare nine-digit number is a phone only with a mobile prefix or a label in front.
  It stays when it ends in `000` (`450 000 000`), has a currency in front (`PLN`, `€`, `$`) or a currency,
  `mln`, `tys.`, `%` or a count (`osób`, `mieszkańców`) behind it, is the tail of a longer number
  (`1 600 123 456 zł`) or the head of one (`600 123 456 789`), or has decimals (`600123456,50`). A label
  such as `tel.` beats the `000` rule or the count rule alone (`tel. 600 100 000` and `tel. 600 123 456
  osoby, która dzwoniła` are masked), not both together (`liczba telefonów 226 000 000 sztuk`) and not
  the currency rule. A dashed number (`600-100-200`) is masked wherever it stands.
- Ids in a URL (`/artykul/600123456`, `?id=600123456`, `/tytul,600123456.html`), unless a label such as
  `phone=` says it is a phone, and ids with a letter behind the digits (`gus-532015686e`). A number
  after `REGON` stays too (a REGON can start like a mobile number).
- A register number without a valid PESEL checksum, a code that fails the ID card check digit, a
  currency code in front of an amount (`PLN 123456`), an acronym and a space in front of an amount that
  happens to pass the check digit (`NFZ 100000 zł`, `GUS 550000 osób`) and a phrase such as `nr 1234567`
  (a passport number has no space and capital letters).

What this can get wrong: a random 11-digit number passes the PESEL checksum 1 time in 10 and a random
3-letters-6-digits code passes the ID card check digit 1 time in 10, so both are sometimes masked
although they are not personal data. The passport pattern has no check digit: UNCONFIRMED, the two
unofficial descriptions we found put it in different places (3rd or last character). So any 2 capital
letters and 7 digits are masked, an invoice code such as `FV1234567` too. A bare number that is not a
phone but starts with a mobile prefix and has no currency or count next to it is masked (`512 345 678
użytkowników`). Not detected: a landline without a country code, brackets or a label, a bare mobile
number ending in `000` or followed by a count (`600 123 456 osoby starsze`), a number with `48` but no
`+`, an ID card number in lower case or one with a space and a unit behind it (`ABC 412345 osób`), and a
bare number directly followed by more digits, labelled or not (`600 123 456 601 234 567`, `tel. 600 123
456 2024`; with a country code, or dashed, every number is masked).

No library fits (checked 2026-11-22). Presidio (presidio-analyzer 2.2.366): its only Polish recognizer
is PESEL, which this module already covers (an ID card recognizer is an open pull request, #2444), and
it needs spaCy plus a language model. python-stdnum 2.2 has `pl` modules for NIP, PESEL and REGON only:
no ID card or passport. phonenumbers 9.0.44 reports `123456789 zł` and `500 000 000 zł` as valid
Polish numbers, so it would mask the amounts. polish-pii-recognizers (GitHub only, needs Presidio) and
polanon (a whole masker with its own rules) were created in October and November 2026, and we did not
take them. We kept the module. The ID card check digit follows the Polish Wikipedia article "Dowód
osobisty w Polsce" (we found no official specification) and is tested against vectors from other
projects' test suites. The mobile prefixes are the 13 mobile ones of the numbering plan (Dz.U. 2024
poz. 1862). libphonenumber's Polish metadata has the same plus the range 21x, which the plan assigns to
machine-to-machine services, so we left it out.

Where masking runs:

| Call site | Masked? | Why |
|---|---|---|
| Text sent to Claude for claim extraction (`verifier.verify_text`), pasted text and the text of a linked page | yes | A placeholder keeps the sentence, so claims still split. A claim about the personal data itself (for example "this account belongs to the charity") can no longer be checked from the number, which is the point. The claim and source sentence shown to the user carry the placeholder. |
| Everything after extraction (`prawdowid/pipeline.py`, #11): web search, Google Fact Check, EUvsDisinfo, rerank, judge | yes, by construction | These steps take the claims and queries the model wrote from the masked text. Web search queries (`websearch.search_web`) and database queries (`cache.build_tsquery`) are masked again. |
| Check log record (`checklog.record`) | yes | The question, the claims, the unchecked claims and the source URLs are masked again when the record is written, so a call site that forgets to mask cannot leak into the log. |
| stdout log lines | yes | No raw user text: session id, channel, status, lengths, token counts, and the claims and search queries of each check (written by the model from the masked text, so a name can still appear). Link URLs are masked (an e-mail in a query string), fetch errors are logged by type only. On top of that, every line of the `prawdowid` and `prawdowid.discord` loggers, tracebacks included, goes through `privacy.MaskingFilter` (set in `prawdowid/app.py` and `prawdowid/discord_bot.py`; uvicorn's own error log is not covered), so an unexpected exception that carries raw input is masked too. |
| The link itself, when it is fetched | no | We need the real address to fetch the page. |
| Evidence fragments from source pages | no | They are public pages, and the quote must match the page word for word. |

## What a check stores

One JSON line in the check log (`PRAWDOWID_CHECK_LOG`, default `logs/checks.jsonl`, in Docker
`/var/lib/prawdowid/checks.jsonl` on the named volume `checklog`, so a redeploy keeps it), written by `POST /api/checks` for
every check, also a failed or timed-out one (#14): session id, start and end time, total latency,
channel, the masked question, status, `error` (`"timeout"` when the API's 60 s limit fired, or the exception class when verify raised;
`null` when the pipeline returned a notice, also its own 40 s budget cut), the notice message, the masked page URL and content hash for a link, the
time of each step (`fetch`, `extract`, and per claim `factcheck`, `euvsdisinfo`, `web`, `rerank`,
`judge`, `retry_*`), every model answer (model name, input and output tokens), `cost_usd`, security
events (kind, location and detector, never the wording), ids of matched incidents, check-level
limitations, each claim with its
verdict, sources (masked URL and source type) and limitations (search errors, time limit), and the
claims left unchecked. Page text from a link is not stored. `GET /api/sessions/{id}` returns the
records of one session as stored. A check cut by the API's 60 s limit (the pipeline's own 40 s budget
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
| jsDelivr CDN (`cdn.jsdelivr.net`) | The visitor's IP address and browser details, sent by their own browser. The request carries no check text and no session id. | Only on the API docs page `/api/docs`, which loads Swagger UI from there. The web page itself loads nothing third-party; its Content-Security-Policy forbids it. |

The region where each provider processes the data is UNCONFIRMED: we have not checked their data
residency terms for this demo.
