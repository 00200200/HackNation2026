# Privacy

What we keep about a check, for how long, where text goes, and how to delete it (issue #17,
brief section 5).

This page describes `integration/r4` (22.11.2026), the demo build. `main` (`1aa173f`) is its ancestor and lacks
these changes, so for `main` read the lines below as follows: masking does not cover ID card and passport
numbers and masks fewer phone formats
([#82](https://github.com/00200200/HackNation2026/issues/82)); the check log is not on the `checklog` volume
(`/var/lib/prawdowid/checks.jsonl`, meant to survive a deploy, not verified on the server,
[#70](https://github.com/00200200/HackNation2026/issues/70)); the whole-check budget is 25 s, not 40 s
([#63](https://github.com/00200200/HackNation2026/issues/63)); there is no result cache, so no ready answer
stays in memory ([#59](https://github.com/00200200/HackNation2026/issues/59)); there is no Tavily query cache
(#110), the default extraction model is Opus (#88), Google Fact Check gets one query per claim, not up to 8
(#100), and there are no moderator cases (#79). After a change to `integration/r4` this page needs a recheck.
In `integration/r4` a ready answer for the same text stays 30 minutes in process memory, shared by both
channels, and the delete button does not remove it.

#113 in `integration/r4` changes the masking in two ways that let more through, and masks the corpus text when
the corpus is built. A card number is left alone when it follows a product label (EAN, GTIN, UPC, SKU, "kod",
"nr", "numer", "partii", "lot", "id"), sits in a URL, or is 13 digits with a valid EAN-13 check digit; a card
word (karta, card, visa, mastercard, maestro) right in front of the number wins over such a label. So
`nr 4111 1111 1111 1111` goes to the model as typed, while `numer karty 4111 1111 1111 1111` and
`karta nr 4111 1111 1111 1111` are masked. `main` masks all of them. The check log writes the question through
the same function, so a number that stays reaches it unmasked and stays 30 days. The stdout logs call it too
and carry the claims and queries, so the number can reach them when a claim carries it. The searches call it as
well (Tavily, Google Fact Check and www.gov.pl queries), so the number can reach those processors if the model
copies it into a claim or a query; we did not test whether it does. The three sample strings above were run
through `mask_personal_data` of `integration/r4` on 22.11.2026; where it is called was read in the code. A bare
nine-digit number also stays when it looks like an amount or an id (a currency next to it, a count behind it,
000 at the end, a REGON label or a URL around it).

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
| Card number | 13–19 digits, in one run or groups of four, Luhn valid; not after a product label (EAN, GTIN, kod kreskowy, numer partii), not inside a URL, not a 13-digit run with a valid EAN-13 check digit | `[numer karty]` |

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

What this can get wrong: a 14 to 19 digit product or document id that passes Luhn (1 in 10) and has no label or URL around it is masked as a card; a random 11-digit number passes the PESEL checksum 1 time in 10 and a random
3-letters-6-digits code passes the ID card check digit 1 time in 10, so both are sometimes masked
although they are not personal data. The passport pattern has no check digit: UNCONFIRMED, the two
unofficial descriptions we found put it in different places (3rd or last character). So any 2 capital
letters and 7 digits are masked, an invoice code such as `FV1234567` too. A bare number that is not a
phone but starts with a mobile prefix and has no currency or count next to it is masked (`512 345 678
użytkowników`). Not detected: a landline without a country code, brackets or a label, a bare mobile
number ending in `000` or followed by a count (`600 123 456 osoby starsze`), a number with `48` but no
`+`, an ID card number in lower case or one with a space and a unit behind it (`ABC 412345 osób`), and an
unlabelled bare number directly followed by more digits (`600 123 456 601 234 567`). A label masks the
first nine digits only (`tel. 600 123 456 2024` → `tel. [telefon] 2024`; `tel. 600 123 456 601 234 567`
→ `tel. [telefon] 601 234 567`), and a currency or a count behind a longer run of digit groups still
makes an amount (`telefonów 226 000 000 000 sztuk` stays). With a country code, or dashed, every number
is masked.

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
| Everything after extraction (`prawdowid/pipeline.py`, #11): web search, Google Fact Check, EUvsDisinfo, rerank, judge | yes, by construction | These steps take the claims and queries the model wrote from the masked text. Web search queries (`websearch.search_web`), Fact Check keys (`factcheck.keys_for`) and database queries (`cache.build_tsquery`) are masked again. |
| Check log record (`checklog.record`) | yes | The question, the claims, the unchecked claims and the source URLs are masked again when the record is written, so a call site that forgets to mask cannot leak into the log. |
| Evidence corpus (`corpus/evidence.jsonl`, `prawdowid/corpus_bm25.py`) | yes, at build time | `corpus.sources.base.make_doc` masks title, text, claim and rating (`corpus.schema.mask_personal`) before a record exists, and `make corpus-check` fails on anything `mask_personal_data` would still change. Public switchboard numbers are masked too. Git history keeps the pre-22.11 record with a named person's mobile number (#112/#113: history decision open). |
| stdout log lines | yes | No raw user text: session id, channel, status, lengths, token counts, and the claims and search queries of each check (written by the model from the masked text, so a name can still appear). Link URLs are masked (an e-mail in a query string), fetch errors are logged by type only. On top of that, every line of the `prawdowid` and `prawdowid.discord` loggers, tracebacks included, goes through `privacy.MaskingFilter` (set in `prawdowid/app.py` and `prawdowid/discord_bot.py`; uvicorn's own error log is not covered), so an unexpected exception that carries raw input is masked too. |
| The link itself, when it is fetched | no | We need the real address to fetch the page. |
| Evidence fragments from source pages | no | They are public pages, and the quote must match the page word for word. |

## What a check stores

One JSON line in the check log (`PRAWDOWID_CHECK_LOG`, default `logs/checks.jsonl`, in Docker
`/var/lib/prawdowid/checks.jsonl` on the named volume `checklog`, so a redeploy keeps it), written by `POST /api/checks` for
every check, also a failed or timed-out one (#14): session id, start and end time, total latency,
channel, the masked question (a link without its secret query values), status, `error` (`"timeout"` when the API's 60 s limit fired, or the exception class when verify raised;
`null` when the pipeline returned a notice, also its own 40 s budget cut), the notice message, the masked page URL and content hash for a link, the
time of each step (`fetch`, `extract`, and per claim `factcheck`, `euvsdisinfo`, `web`, `rerank`,
`judge`), every model answer (model name, input and output tokens), `cost_usd`, security
events (kind, location and detector, never the wording), ids of matched incidents, check-level
limitations, each claim with its
verdict, sources (masked URL and source type) and limitations (search errors, time limit), the
claims left unchecked, and the moderator case the check joined (`moderator_case`, see below). Page
text from a link is not stored. `GET /api/sessions/{id}` returns the
records of one session as stored. A check cut by the API's 60 s limit (the pipeline's own 40 s budget
normally ends it first), or one where verify raised, keeps its total latency, `error`, the notice
and the pattern-only screening: the steps and model calls it had made are lost with the cancelled
task.

## Moderator cases

Brief section 2 asks that questions the sources cannot settle reach a person the administrator
names. `prawdowid/cases.py` keeps them as moderator cases (#79, scenario H). While
`PRAWDOWID_ADMIN_TOKEN` is set, the API files a check when a checked claim ends `brak
wystarczających dowodów`, when the check logged a security event,
or when a claim about evacuation or an RCB alert, a health emergency, elections or mobilisation (a
short list in code) ended false, misleading or without enough evidence. A question with a similar
claim joins the open case and raises its count (shared word stems, `PRAWDOWID_CASE_MIN_SIMILARITY`,
default 0.5).

Each case (`PRAWDOWID_CASES`, default `cases.jsonl` next to the check log, so in Docker
`/var/lib/prawdowid/cases.jsonl` on the `checklog` volume) stores its number and opening time and,
for each question in it, the session id, time, channel, why it was filed, the masked claims (for a
check without claims, the first 300 characters of the masked question; for a link, its URL without
secret query values), the masked page URL of a link, the lookups that ran and the URLs they found.
Claims are masked again right before the write. The last case number sits in `cases.seq`, so no
number is given twice.

The administrator decides who reads the cases: they give `PRAWDOWID_ADMIN_TOKEN` to a moderator or
an analyst, who calls `GET /api/cases` with `Authorization: Bearer <token>`. Without the variable
nobody can read the cases, so there is no queue: no check is filed, no answer mentions a moderator
and the route does not exist (404). The list shows the open cases, the most asked first, with counts,
the first and last question time, the claims, channels, lookups and URLs. It never shows session
ids. Nobody is told when a case opens: there is no e-mail or webhook, so the moderator has to read
the list.

The person who asked gets `moderator_case` in the answer (number, `created` or `updated`, count).
The web page, `/czat` and Discord say "Zgłoszenie trafiło do kolejki moderatora (sprawa N)" only
after the case was written. When the write fails, the API logs the failure and the answer says
nothing about a moderator. The count also tells the asker how many similar questions the case
holds, which reveals that someone else asked something similar in the last 30 days.

Web search in a check also adds the public pages it fetched to the source cache
(`corpus/docs.jsonl`). Those are public pages with no session id, not the user's text, though a
page found for a claim can contain the same words or personal data as the question. A check never writes the
PostgreSQL source store (written only by the seed script; step 2c is off in the pipeline).

## Retention

One constant, `RETENTION_DAYS = 30` in `prawdowid/privacy.py`:

- Check log: records older than that are dropped when the next check is written (so with no new
  checks they stay until one comes). Damaged lines are dropped the same way.
- Moderator cases: each question in a case is dropped that long after it was asked, when the next
  question is filed or a session is deleted (the admin view hides it at once); a case left without
  questions goes with it.
- Source cache `corpus/docs.jsonl`: pages fetched more than that ago are dropped on the next save.
- Search cache `corpus/search_cache.jsonl` (`prawdowid/search_cache.py`, #110): the hits Tavily
  returned for a query (URL, title, snippet, publication date), under a SHA-256 of the normalised
  masked query, domains and limit. The query text is not stored. Entries live
  `PRAWDOWID_SEARCH_CACHE_TTL_S` seconds (default 86400, capped at `RETENTION_DAYS`; 0 turns the cache
  off) and are dropped from the file when it is next loaded. Failures and limit answers are not cached.
  The entries are public search results, not the user's text, but they can hold the same words or
  personal data a user submitted: the claim sentence the model wrote from the masked text is itself
  a query, and a snippet that matches it can repeat a name or a number from it. "Usuń moje
  sprawdzenia" does not reach this cache, so such a snippet stays until its entry expires (24 h by
  default) and leaves the file.
- Source store: each page gets `delete_after = now() + RETENTION_DAYS` on insert. Search and
  `stored_documents()` skip expired pages at once, but the rows are only deleted when
  `delete_expired_documents()` runs, and only the seed script runs it (before it writes). The seed
  script is the only writer, so expired pages stay in the database until the next seed. Before step
  2c is switched on, run it on a schedule (cron or `pg_cron`).
- Result cache (`prawdowid/app.py`, #59): the finished answer for a text is kept in the API
  process's memory for 30 minutes (at most 500 answers), under a hash of the normalised input, so
  the same text from the web form and from Discord gets the same answer. The answer holds the
  claims and the sentences they came from. It is never written to disk, a restart empties it, and
  "Usuń moje sprawdzenia" does not reach it. After 30 minutes an answer is no longer reused, but an
  expired entry can stay in process memory until the next write to the cache evicts it; the 30
  minutes is not a promise of deletion from memory. A fast answer shows that the
  same text was checked in the last 30 minutes (response header `X-Cache: hit`), whoever sent it.
  This is not governed by `RETENTION_DAYS`.

Not covered: Docker's own stdout logs (rotation is set by the Docker host). They carry no raw user
text: claims, queries and link URLs, all from masked text.

## Demo session and deletion

The API gives every check a session id in the `X-Session-Id` response header. A client that sends
the header back keeps the same session. The web page keeps it in `sessionStorage` (until the tab
closes) and shows "Usuń moje sprawdzenia", which calls `DELETE /api/sessions/{id}` and removes every
check log record of that session and its questions in the moderator cases (a case left without
questions goes too). The answer is `{"deleted": <check log records>, "withdrawn": <questions taken
out of moderator cases>}`. When `withdrawn` is above 0, the web page and `/czat` also say the
questions were withdrawn from the moderator's queue.
The session id is a bearer token: anyone who has it can read (`GET /api/sessions/{id}`) and
delete that session's records; there is no other login.

Discord sends no session id, so each Discord check gets its own session. The bot neither sends nor reads
the `X-Session-Id` header and shows no id (`prawdowid/discord_bot.py`, checked on `main`, at `ca48b84`, in `integration/r4` and in PR #73 at `bec64ff`),
and the check log holds no Discord user id. A Discord user therefore cannot name their session, and there
is no command or other self-service route for them ([unsupported.md](unsupported.md)). Only someone with
access to the check log can find a session (by channel, time and masked text) and delete it with the API
call. The repository names no contact for a deletion request, and no decision on one is recorded (UNCONFIRMED). The check log
expires after 30 days (see Retention above), which removes the record in time but is not a deletion route.

## Where data is processed

Issue #85. The table comes from each provider's own terms and documentation, read on 22.11.2026
(links in the last column). A cell says UNCONFIRMED where those pages are silent or did not load.
Nothing here was tested by sending data to a provider, and no model or eval was run for this page.
What a processor receives is limited by the masking above: e-mail, NRB and IBAN, card, PESEL and
phone are replaced before the model (`main` lacks ID card and passport numbers and some phone
formats, and `integration/r4` leaves a card number after a product label such as "nr" unmasked), names and
addresses are not.

### Processors

| Processor and step | What it receives | Where it processes | Retention and training | Terms |
|---|---|---|---|---|
| Anthropic API (Claude): extraction, rerank, judge. Every check. | Extraction: the pasted text or the text of a linked page, masked, up to 5000 characters. Rerank and judge: the masked claim and public evidence fragments. | The default `inference_geo` is `global`, and Anthropic says it may route traffic by default to select countries in the US, Europe, Asia and Australia ([where its servers are](https://privacy.claude.com/en/articles/7996890-where-are-your-servers-located-do-you-host-your-models-on-eu-servers), 15.06.2026), with storage in the US. The only other setting is `us`. The first-party API has no EU-only option. The EEA contract partner is Anthropic Ireland, transfers rest on SCCs. | The Privacy Center says inputs and outputs are deleted from the backend within 30 days (content flagged by policy checks may stay up to 2 years). The API docs say content is not retained by default except for some models (30 days). The two pages disagree: which one applies to us is UNCONFIRMED. The Commercial Terms bar training on Customer Content. | [Commercial Terms](https://www.anthropic.com/legal/commercial-terms), [DPA](https://www.anthropic.com/legal/data-processing-addendum) (SCC modules 2 and 3), [Privacy Policy](https://www.anthropic.com/legal/privacy), [data residency](https://platform.claude.com/docs/en/manage-claude/data-residency), [retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data). The sub-processor list did not render: UNCONFIRMED. |
| Tavily web search (`/search`). Every checkable claim, when `TAVILY_API_KEY` is set, and the corpus builder. | The search queries the model wrote from the masked text (2 per claim), the claim sentence, one search of the claim restricted to the fact-checker domains, and the masked claim itself when the model wrote no queries (#106; there is no second search), the domain allowlist, `language=pl` and our API key. No page text: we fetch pages ourselves. A query repeated within `PRAWDOWID_SEARCH_CACHE_TTL_S` (24 hours by default) is answered from our cache and not sent again (#110). | United States: the help center says the infrastructure is primarily there, cloud provider not stated. An EU endpoint (`api.eu.tavily.com`, API in Germany, index in France) is open to selected customers only. Tavily has belonged to Nebius since 19.02.2026, and says its terms and contracting entity did not change. | No retention period is stated. With the account setting "Allow Use of Query Data" off, queries are not stored or used for improvements. Its default is not stated and we have not checked ours: UNCONFIRMED. The EU endpoint page lists zero query retention as an account setting there, not as the default; for the global endpoint it is not stated: UNCONFIRMED. Terms §6.5 let Tavily and its AI providers train on Customer Input submitted to its "AI Functionality" (§6.1: generative research tools), which does not name `/search`, so whether it covers our queries is UNCONFIRMED. §1.3 counts queries as Customer Input. §9.2 gives Tavily a perpetual, irrevocable and sublicensable licence over Customer Input, not limited to the AI Functionality, to provide and improve its services and its other products and for market and product research. Terms §8.2 bar government-issued identification numbers (a), payment card information subject to PCI DSS (i) and special categories of data (l) in Customer Input. Our masking does not detect names or health content, on `main` it does not mask ID card or passport numbers, and it can let a card number through (see the scope note at the top). | [Terms](https://tavily.com/terms) (4.05.2026), [Privacy](https://tavily.com/privacy), [GDPR and DPA](https://help.tavily.com/articles/8202749643-gdpr-dpa-security-documentation), [query data setting](https://help.tavily.com/articles/4205958832-understanding-the-allow-use-of-query-data-setting), [EU endpoint](https://www.tavily.com/eu). A DPA exists on request, whether we hold one is UNCONFIRMED. |
| Google Fact Check Tools (`claims:search`). Every checkable claim, when `GOOGLE_FACTCHECK_API_KEY` is set. | The masked claim text, `languageCode` and our API key. Up to 8 short queries per claim instead of one (#100; `main` sends one): the claim, the names in it, quoted spans and the search queries, each masked again. | Not stated for this API. Google's privacy policy says its servers are worldwide, the EEA controller is Google Ireland. | Not stated for API requests. The API Terms let Google monitor use of the APIs to improve its products (§3.a) and use submitted information as its privacy policies say (§7.a). Training use for this API is not stated. | [API Terms](https://developers.google.com/terms), [Privacy Policy](https://policies.google.com/privacy), [controller-to-controller terms](https://business.safety.google/controllerterms/) (DPF and SCCs). There is no processor DPA. |
| EUvsDisinfo MCP (`mcp.euvsd.info`). Every checkable claim, when `EUVSDISINFO_API_KEY` is set. | The claim text as a search query, cut to 200 characters, and our API key. | Not stated. The landing page is also served from a Vercel hostname, so Vercel hosting is likely but unstated. The operator is the EEAS East StratCom Task Force. | Not stated for MCP requests, server logs or training. | No terms found for the MCP, access is by request ([about](https://euvsdisinfo.eu/about/)). The [EEAS privacy notice](https://euvsdisinfo.eu/eeas-privacy-statement-data-protection-notice/) covers the website, newsletter and feedback, not the MCP. |
| www.gov.pl search. Every checkable claim, unless `PRAWDOWID_GOVPL=0`. | The keyword queries the model wrote for the claim, or its first web query when it wrote none, or the claim text itself when it wrote no web queries either (`/api/data/search?query=`), then GET requests for the result pages. The site sees our server's address. | Not stated. The portal operator is the Minister Cyfryzacji. | Request logging and retention are not stated. There is no portal-wide privacy policy: each unit publishes its own. | [Copyright page](https://www.gov.pl/web/gov/prawa-autorskie) (text under CC BY-SA 4.0), [cookie policy](https://www.gov.pl/web/gov/polityka-dotyczaca-cookies). No rule on automated access found. The endpoint is undocumented and its stability is UNCONFIRMED. |
| OVHcloud VPS, Limburg (DE). Hosts everything. | Everything the app holds: masked claims in the check log, the source cache, PostgreSQL data, proxy logs, and every request in transit. | Germany, Limburg (region eu-west-lim). The VPS terms fix the location at order time. OVHcloud and its sub-processors may process content remotely, and the sub-processor list names OVH affiliates in Canada and the UK. Whether they touch VPS data, and which OVH entity our account is under, is UNCONFIRMED (the invoice says). | On termination OVHcloud deletes all content and backups irreversibly (General Terms §6.5), with no number of days stated. Our own retention is 30 days for the check log and the cache, and Docker's logs sit outside it. The DPA limits OVHcloud's use of content to what the services need (§4.1). | [VPS conditions](https://contract.eu.ovhapis.com/1.0/pdf/Conditions_Particulieres_VPS-pl.pdf), [DPA](https://contract.eu.ovhapis.com/1.0/pdf/OVH_Data_Protection_Agreement-pl.pdf) (Art. 28 GDPR, SCCs for transfers to countries without adequacy), [sub-processors](https://contract.eu.ovhapis.com/1.0/pdf/OVH_Sub_processors-pl.pdf). |
| Discord, when the bot runs (#59 says it is not deployed, which we did not check). | The text a user types into `/sprawdz`, which Discord already holds, and our reply posted in the channel. | United States: Discord says it stores and processes information on servers there. The EEA controller is Discord Netherlands BV, transfers rest on SCCs and the Data Privacy Framework. | Discord keeps information until it decides it is no longer needed, and deleted messages leave backups after 30 to 45 days. Retention of slash-command payloads is not stated: UNCONFIRMED. The Developer Policy bars developers from training AI on message content obtained through the APIs. | [Developer Terms](https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service), [Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy), [Privacy Policy](https://discord.com/privacy). The Developer Terms (§5) require a privacy policy that says how users can request deletion and links from the application (§5.a), and an easily accessible way for users to ask for their API Data to be deleted (§5.b). A Discord user has no usable deletion route today (see "Demo session and deletion" above), and the bot code shows no link to a privacy policy (whether the Developer Portal entry has one is UNCONFIRMED), so we do not claim these requirements are met. |
| The sites a link or a search result points to. | A GET request from our server's address for the URL, with an identifying user agent (`Prawdowid/0.1` for a pasted link, `PrawdowidBot/0.1` for search results) and no check text. For a link the user pasted, the URL goes out as it was pasted, unmasked: whatever sits in its path or query string (a name, an e-mail, an id) reaches the site, and our masking does not touch it. Only the copy in our logs is masked, with secret-looking query values replaced. The fragment (`#...`) is never sent by HTTP, and a link with a user name or password in it is refused before any request. Redirects are followed, up to 3, and each hop is requested the same way. For a search result the URL comes from the search provider, not from the user. | The site's own hosting. | Not ours to control. Public pages fetched as evidence are cached as metadata for 30 days (Retention above). | The site's own terms. |
| jsDelivr CDN (`cdn.jsdelivr.net`). Only on the API docs page `/api/docs`. | The visitor's IP address and browser details, sent by their own browser. The request carries no check text and no session id. | Not stated here (a CDN): UNCONFIRMED. | Not ours to control. | The web page itself loads nothing third-party; its Content-Security-Policy forbids it. |

Local only: the incident base (`prawdowid/incidents.py`, a local file that receives the raw input and the final URL, nothing leaves the server) and the evidence corpus search
(BM25 in memory over `corpus/evidence.jsonl`, no embedding model and no network, #74; on
`main` checks do not search the corpus). The moderator cases (#79) stay on the same volume as the check log.

### What leaves the EEA today

With the defaults every check sends data outside the EEA, or to places the providers do not state.
Outside the EEA, by the providers' own documents: the three model steps go to Anthropic (global
processing, storage in the US) and web search goes to Tavily (US). The Discord channel adds the US
when it runs. Location not stated, so UNCONFIRMED either way: Google Fact Check (Google's privacy
policy says its servers are worldwide, which does not say where this API runs), EUvsDisinfo and
www.gov.pl. A link pasted by a user also sends its URL to the site it points to. Only the VPS is
fixed in the EEA. Extraction matters most: it is the only step that sees the user's text. Rerank and
judge see the claims and public page fragments.

### Migration path to an EU-processed model

Provider facts below were read on 22.11.2026. No model and no eval was run for this path, so it is
a plan from documentation, not a result.

1. How the model is chosen. Three variables, read when the module loads and passed to PydanticAI as
   model strings: `PRAWDOWID_MODEL` for extraction (`prawdowid/verifier.py`, default
   `anthropic:claude-sonnet-5-5` since #88; `main` still `anthropic:claude-opus-5-5`),
   `PRAWDOWID_RERANK_MODEL` (`prawdowid/rerank.py`, default
   `anthropic:claude-haiku-5-5`) and `PRAWDOWID_JUDGE_MODEL` (`prawdowid/judge.py`, default
   `anthropic:claude-sonnet-5-5`). The three agents use native structured output and have no tools.
2. Same Claude models, in the EU: Amazon Bedrock. Anthropic's own API has no EU setting, but
   Bedrock serves Opus, Sonnet and Haiku 5.5 through EU geographic inference profiles that stay in
   EU regions (from eu-central-1: Frankfurt, Stockholm, Milan, Spain, Ireland, Paris), as the
   model cards for [Opus 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html),
   [Sonnet 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html) and
   [Haiku 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html)
   list them. Steps:
   - In `pyproject.toml` change `pydantic-ai-slim[anthropic,mcp]` to
     `pydantic-ai-slim[anthropic,bedrock,mcp]`, then `uv lock` and rebuild the image.
   - Set `PRAWDOWID_MODEL=bedrock:eu.anthropic.claude-opus-5-5`,
     `PRAWDOWID_RERANK_MODEL=bedrock:eu.anthropic.claude-haiku-5-5`,
     `PRAWDOWID_JUDGE_MODEL=bedrock:eu.anthropic.claude-sonnet-5-5`, `AWS_DEFAULT_REGION=eu-central-1`
     and either `AWS_BEARER_TOKEN_BEDROCK` or `AWS_ACCESS_KEY_ID` with `AWS_SECRET_ACCESS_KEY`. For
     the Sonnet default of #88, set `PRAWDOWID_MODEL=bedrock:eu.anthropic.claude-sonnet-5-5`.
   - Of the model settings and credentials, `compose.yaml` forwards only `PRAWDOWID_MODEL` and
     `ANTHROPIC_API_KEY` to the backend, and none of the `PRAWDOWID_*_THINKING` variables (#106). Add the other two
     model variables and the AWS ones to its `environment:` list, or they never reach the container.
   - With a current `boto3`, native structured output keeps working, because PydanticAI gives these
     model names the same profile. A `botocore` that predates Converse `outputConfig` makes our
     `NativeOutput` agents raise a `UserError` (`pydantic_ai/models/bedrock.py`), so install the
     `bedrock` extra and keep `boto3` current. AWS warns that the profile prefix alone does not
     prove where a request runs: check the routing with `GetInferenceProfile`.
   - Bedrock ignores the `max_retries` setting that our three agents pass (PydanticAI lists it as
     unsupported for Bedrock and warns), so botocore's own retry defaults apply. `request_timeout`
     (45 s for extraction, 20 s for the judge, 10 s for rerank), which PydanticAI enforces for
     every model, still caps each request. This is the one setting that changes behaviour; the
     move is otherwise expected to need no prompt change.
   - UNCONFIRMED: access criteria for the 5.5 models on Bedrock, their default data retention
     there, and whether a long-term Bedrock API key works with `eu.` model IDs.
3. Fallback: Google Vertex AI, `eu` multi-region (about 10% dearer). It is not env-only: it needs
   an `AsyncAnthropicVertex(region="eu", ...)` client passed to `AnthropicProvider` in code, and
   the `anthropic[vertex]` extra. Google stores data at rest in the region but says processing may
   vary, so in-EU processing is not guaranteed by the pages we read. Microsoft Foundry has no EU
   zone for Claude (global or US only).
4. Non-Claude EU providers: Mistral on `api.eu.mistral.ai`, OVHcloud AI Endpoints and IONOS AI
   Model Hub (Germany). OVHcloud is a built-in PydanticAI provider: `ovhcloud:<model>` with
   `OVHCLOUD_API_KEY` and the `openai` extra. As with Bedrock, `compose.yaml` must forward that key
   and the two other model variables. Mistral on its EU endpoint needs a provider object built in
   code (its base URL is not an environment variable), not only a model string, and PydanticAI
   2.71.0 raises an error for native structured output on Mistral models, whose profile does not
   enable it, so those agents would need tool or prompted output. IONOS lists an OpenAI-compatible
   API (UNCONFIRMED: its documentation was not read for this page). If so, PydanticAI's OpenAI
   provider reads the base URL from `OPENAI_BASE_URL`, so `openai-chat:<model>` may need no code (a
   bare `openai:` string selects the Responses API, which such an endpoint may not offer). Whether
   IONOS accepts the JSON-schema output our agents use is also UNCONFIRMED, and none of this was
   run. No page we read gives Polish quality figures for these models. Switch a
   step only after `uv run python -m evals.run` shows parity on Polish, and that run does not
   exist (#16).
5. What stays outside the EEA after step 2: web search (Tavily, US) and the Discord channel (US).
   Fact Check (Google), EUvsDisinfo and www.gov.pl may or may not be in the EEA: none says, so they
   stay UNCONFIRMED. If only one model step can move first, move extraction.
