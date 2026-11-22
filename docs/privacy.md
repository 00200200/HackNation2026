# Privacy

What we keep about a check, for how long, where text goes, and how to delete it (issue #17,
brief section 5).

This page describes `main`, except where a line names a pending change. PR #109 changes four things
here: masking also covers ID card numbers (`[numer dowodu]`) and passport numbers
(`[numer paszportu]`), and a phone number is masked when it has a country code, dashes or an area code
in brackets, or is nine digits that start with a mobile prefix or follow a label such as "tel."
([#82](https://github.com/00200200/HackNation2026/issues/82)); the check log moves to the `checklog` volume at
`/var/lib/prawdowid/checks.jsonl`, which is meant to survive a deploy (not verified on the server,
[#70](https://github.com/00200200/HackNation2026/issues/70)); the whole-check budget is 40 s, not 25 s ([#63](https://github.com/00200200/HackNation2026/issues/63)); a ready
answer for the same text stays 30 minutes in process memory, shared by both channels, and the delete
button does not remove it ([#59](https://github.com/00200200/HackNation2026/issues/59)). `integration/r3` (a local branch in state
`235209b`, no PR) adds a Tavily query cache (#110) and Sonnet as the default extraction model (#88).

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

Issue #85. The table comes from each provider's own terms and documentation, read on 22.11.2026
(links in the last column). A cell says UNCONFIRMED where those pages are silent or did not load.
Nothing here was tested by sending data to a provider, and no model or eval was run for this page.
What a processor receives is limited by the masking above: e-mail, NRB and IBAN, card, PESEL and
phone are replaced before the model (PR #109 adds ID card and passport numbers and more phone
formats), names and addresses are not.

### Processors

| Processor and step | What it receives | Where it processes | Retention and training | Terms |
|---|---|---|---|---|
| Anthropic API (Claude): extraction, rerank, judge. Every check. | Extraction: the pasted text or the text of a linked page, masked, up to 5000 characters. Rerank and judge: the masked claim and public evidence fragments. | The default `inference_geo` is `global`, and Anthropic says it may route traffic by default to select countries in the US, Europe, Asia and Australia ([where its servers are](https://privacy.claude.com/en/articles/7996890-where-are-your-servers-located-do-you-host-your-models-on-eu-servers), 15.06.2026), with storage in the US. The only other setting is `us`. The first-party API has no EU-only option. The EEA contract partner is Anthropic Ireland, transfers rest on SCCs. | The Privacy Center says inputs and outputs are deleted from the backend within 30 days (content flagged by policy checks may stay up to 2 years). The API docs say content is not retained by default except for some models (30 days). The two pages disagree: which one applies to us is UNCONFIRMED. The Commercial Terms bar training on Customer Content. | [Commercial Terms](https://www.anthropic.com/legal/commercial-terms), [DPA](https://www.anthropic.com/legal/data-processing-addendum) (SCC modules 2 and 3), [Privacy Policy](https://www.anthropic.com/legal/privacy), [data residency](https://platform.claude.com/docs/en/manage-claude/data-residency), [retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data). The sub-processor list did not render: UNCONFIRMED. |
| Tavily web search (`/search`). Every checkable claim, when `TAVILY_API_KEY` is set, and the corpus builder. | The search queries the model wrote from the masked text (the masked claim itself when it wrote none, and on a second search when the first found too little), the domain allowlist, `language=pl` and our API key. No page text: we fetch pages ourselves. A query repeated within `PRAWDOWID_SEARCH_CACHE_TTL_S` (24 hours by default) is answered from our cache and not sent again (#110, no PR yet). | United States: the help center says the infrastructure is primarily there, cloud provider not stated. An EU endpoint (`api.eu.tavily.com`, API in Germany, index in France) is open to selected customers only. Tavily has belonged to Nebius since 19.02.2026, and says its terms and contracting entity did not change. | No retention period is stated. With the account setting "Allow Use of Query Data" off, queries are not stored or used for improvements. Its default is not stated and we have not checked ours: UNCONFIRMED. Zero retention is available on request. Terms §6.5 let Tavily and its AI providers use Customer Input and Outputs, which include queries, to train and improve AI models. Terms §8.2(l) bar special categories of personal data, and our masking does not detect names or health content. | [Terms](https://tavily.com/terms) (4.05.2026), [Privacy](https://tavily.com/privacy), [GDPR and DPA](https://help.tavily.com/articles/8202749643-gdpr-dpa-security-documentation), [query data setting](https://help.tavily.com/articles/4205958832-understanding-the-allow-use-of-query-data-setting), [EU endpoint](https://www.tavily.com/eu). A DPA exists on request, whether we hold one is UNCONFIRMED. |
| Google Fact Check Tools (`claims:search`). Every checkable claim, when `GOOGLE_FACTCHECK_API_KEY` is set. | The masked claim text, `languageCode` and our API key. | Not stated for this API. Google's privacy policy says its servers are worldwide, the EEA controller is Google Ireland. | Not stated for API requests. The API Terms let Google monitor use of the APIs to improve its products (§3.a) and use submitted information as its privacy policies say (§7.a). Training use for this API is not stated. | [API Terms](https://developers.google.com/terms), [Privacy Policy](https://policies.google.com/privacy), [controller-to-controller terms](https://business.safety.google/controllerterms/) (DPF and SCCs). There is no processor DPA. |
| EUvsDisinfo MCP (`mcp.euvsd.info`). Every checkable claim, when `EUVSDISINFO_API_KEY` is set. | The claim text as a search query, cut to 200 characters, and our API key. | Not stated. The landing page is also served from a Vercel hostname, so Vercel hosting is likely but unstated. The operator is the EEAS East StratCom Task Force. | Not stated for MCP requests, server logs or training. | No terms found for the MCP, access is by request ([about](https://euvsdisinfo.eu/about/)). The [EEAS privacy notice](https://euvsdisinfo.eu/eeas-privacy-statement-data-protection-notice/) covers the website, newsletter and feedback, not the MCP. |
| www.gov.pl search. Every checkable claim, unless `PRAWDOWID_GOVPL=0`. | The keyword queries the model wrote for the claim, or its first web query when it wrote none, or the claim text itself when it wrote no web queries either (`/api/data/search?query=`), then GET requests for the result pages. The site sees our server's address. | Not stated. The portal operator is the Minister Cyfryzacji. | Request logging and retention are not stated. There is no portal-wide privacy policy: each unit publishes its own. | [Copyright page](https://www.gov.pl/web/gov/prawa-autorskie) (text under CC BY-SA 4.0), [cookie policy](https://www.gov.pl/web/gov/polityka-dotyczaca-cookies). No rule on automated access found. The endpoint is undocumented and its stability is UNCONFIRMED. |
| OVHcloud VPS, Limburg (DE). Hosts everything. | Everything the app holds: masked claims in the check log, the source cache, PostgreSQL data, proxy logs, and every request in transit. | Germany, Limburg (region eu-west-lim). The VPS terms fix the location at order time. OVHcloud and its sub-processors may process content remotely, and the sub-processor list names OVH affiliates in Canada and the UK. Whether they touch VPS data, and which OVH entity our account is under, is UNCONFIRMED (the invoice says). | On termination OVHcloud deletes all content and backups irreversibly (General Terms §6.5), with no number of days stated. Our own retention is 30 days for the check log and the cache, and Docker's logs sit outside it. The DPA limits OVHcloud's use of content to what the services need (§4.1). | [VPS conditions](https://contract.eu.ovhapis.com/1.0/pdf/Conditions_Particulieres_VPS-pl.pdf), [DPA](https://contract.eu.ovhapis.com/1.0/pdf/OVH_Data_Protection_Agreement-pl.pdf) (Art. 28 GDPR, SCCs for transfers to countries without adequacy), [sub-processors](https://contract.eu.ovhapis.com/1.0/pdf/OVH_Sub_processors-pl.pdf). |
| Discord, when the bot runs (not deployed yet, #59). | The text a user types into `/sprawdz`, which Discord already holds, and our reply posted in the channel. | United States: Discord says it stores and processes information on servers there. The EEA controller is Discord Netherlands BV, transfers rest on SCCs and the Data Privacy Framework. | Discord keeps information until it decides it is no longer needed, and deleted messages leave backups after 30 to 45 days. Retention of slash-command payloads is not stated: UNCONFIRMED. The Developer Policy bars developers from training AI on message content obtained through the APIs. | [Developer Terms](https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service), [Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy), [Privacy Policy](https://discord.com/privacy). The Developer Terms (§5) require a privacy policy and a deletion route; ours is an API call with the session id (see above). |
| The sites a link or a search result points to. | A GET request from our server's address for the URL, with an identifying user agent (`Prawdowid/0.1` for a pasted link, `PrawdowidBot/0.1` for search results) and no check text. For a link the user pasted, the URL goes out as it was pasted, unmasked: whatever sits in its path or query string (a name, an e-mail, an id) reaches the site, and our masking does not touch it. Only the copy in our logs is masked, with secret-looking query values replaced. The fragment (`#...`) is never sent by HTTP, and a link with a user name or password in it is refused before any request. Redirects are followed, up to 3, and each hop is requested the same way. For a search result the URL comes from the search provider, not from the user. | The site's own hosting. | Not ours to control. Public pages fetched as evidence are cached as metadata for 30 days (Retention above). | The site's own terms. |

Local only: the incident base (`prawdowid/incidents.py`, a local file) and the evidence corpus search
(BM25 in memory over `corpus/evidence.jsonl`, no embedding model and no network, #74 in PR #109; on
`main` checks do not search the corpus).

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
   `anthropic:claude-opus-5-5` on `main` and `anthropic:claude-sonnet-5-5` from #88, no PR yet),
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
     `ANTHROPIC_API_KEY` to the backend. Add the other two model variables and the AWS ones to its
     `environment:` list, or they never reach the container.
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
