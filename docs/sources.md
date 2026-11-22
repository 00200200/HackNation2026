# Source list

The committed evidence corpus (`corpus/evidence.jsonl`, built without any key from an audited
catalogue of official sources and fact-checkers, searched by `prawdowid/corpus_search.py`) is
described separately in [`docs/corpus.md`](corpus.md). This page covers web search and its cache.

## www.gov.pl site search (`prawdowid/govpl.py`)

Step 2 also searches www.gov.pl itself, next to Fact Check, EUvsDisinfo and web search, when
`PRAWDOWID_GOVPL` is `1` (the default; `0` switches it off).

| What | Detail |
|---|---|
| Endpoint | `GET https://www.gov.pl/api/data/search?query=<q>&page=1&size=5`: the search endpoint used by the www.gov.pl site itself (undocumented). No key. Not a published public API; its **stability is UNCONFIRMED** and it may change or go away without notice. |
| Why it qualifies | Pages under `www.gov.pl/web/<unit>` are published by ministries and central offices (RCB, MSWiA, KG PSP, GIS, MON, MI, MSZ, KPRM and others): primary `official` sources. Publisher is the unit from the hit's `path` (or the name the page gives itself), publication date is the hit's `publishDate`. |
| How we use it | One search per gov.pl query of a claim (the extraction model writes 1 or 2 keyword queries for claims about the Polish government, capped at 2 in code; otherwise the claim's first web query), at most 5 pages fetched per claim through the same safe fetch as web search (allowlist, public IPs only, robots.txt, 2 MB cap, trafilatura). Our usual User-Agent, an 8 s timeout and one retry on a network error or 5xx, at most 2 searches and 3 page fetches to gov.pl at a time, non-empty search answers cached in process for 10 minutes. A 403, 429 or login is never retried or worked around. |
| On failure | A limitation on the claim ("Wyszukiwarka serwisu gov.pl nie odpowiedziała"), never a verdict. |
| robots.txt | `User-Agent: * / Allow: /` (checked 2026-11-21). |
| Licence | Public sector information; re-use under the Polish act on open data and re-use of public sector information (ustawa z 11.08.2021) and the gov.pl terms: **UNCONFIRMED**, nobody has checked the gov.pl terms yet. We quote short passages with a link, as for every other source. |

Web search leaves `www.gov.pl` (and bare `gov.pl`) pages to this lookup while it is on, so the same
page is not searched twice. The filter is on the host in our code, not Tavily's `exclude_domains`:
Tavily drops a `www.` prefix, so excluding `www.gov.pl` there also dropped `sejm.gov.pl` and every
other `*.gov.pl` site (tested 2026-11-21). While filtering, web search asks Tavily for twice the
results (10) and keeps the first 5 left, since www.gov.pl pages can fill most of a result list. Other `*.gov.pl` sites (Sejm, GUS, PKW, NIK) are not
covered by the gov.pl search and stay in web search.

## Web search

Web search (step 2b, `prawdowid/websearch.py`) only returns pages from the domains below. A host
matches its own entry or the closest parent entry (`nik.gov.pl` falls under `gov.pl`). The list
lives in `ALLOWLIST`; `tests/test_websearch.py` fails when a domain there is missing here.

Every cached document has a title, publisher, retrieval time (`fetched_at`) and, when one can be
found, a publication date (`published_at`, found by trafilatura/htmldate, mostly in page metadata;
falls back to the search provider's own `published_date` when the page carries none; on a page
without date metadata it can come from a date written on the page, so it may be wrong there). A
page with no date anywhere is kept with an empty `published_at`: the answer says "bez daty
publikacji", the verdict lists it as a limitation and an undated source never makes the evidence
"silna" (#95). The per-document list goes to `corpus/manifest.jsonl` when the corpus is built with
`uv run python -m prawdowid.corpus`.
**The corpus is not built yet:** it needs `TAVILY_API_KEY`, which no one on the team has set yet.
Search provider is now **Tavily** (`/search`, official API, see `WORKLOG.md` Decisions, #7, #8);
it replaced DuckDuckGo (`ddgs`), which returned no results from our machine on 2026-11-21.

Tavily results are cached per query (`prawdowid/search_cache.py`, #110) so reruns and repeated
questions spend no credits: key = casefolded, whitespace-folded masked query + sorted domains +
limit; TTL `PRAWDOWID_SEARCH_CACHE_TTL_S` (default 24 h, at most `RETENTION_DAYS`, 0 = off); at most
2,000 entries, persisted in `corpus/search_cache.jsonl`. Failures and limit answers (HTTP 429, 432,
433; the SDK raises `UsageLimitExceededError` or `ForbiddenError`) are never cached; after a limit
answer no call is made for 60 s. Calls and hits are logged per lookup and counted in
`search_cache.STATS` and `search_cache.track()`.

What we store (`prawdowid/cache.py`): metadata of every page we read (URL, title, publisher, dates,
type, domain, licence) in the local file `corpus/docs.jsonl`, owner-only (0600), not in the repo;
never a search snippet of a page we could not read (only the search cache above keeps the provider's
snippet, for its TTL).
Full page text is stored only for a domain whose licence is confirmed (`licence` in `ALLOWLIST`);
today none is, so no page text is archived. The pipeline uses the live text in memory for the
current check only. Records older than 30 days (`RETENTION_DAYS`, by `fetched_at`) are never loaded
and are dropped on every save, a new fetch of the same URL replaces the old record, `delete_document(url)` deletes one
record and deleting the file deletes all. Until licences are confirmed the cache cannot serve as
the eval corpus for citation correctness, which needs the text.

How pages are fetched (`prawdowid/safefetch.py`): every hop, redirects included, must be on the
allowlist, use http(s) on the default port, resolve only to public IP addresses (the connection
goes to the checked address) and be allowed by that host's robots.txt, read with Protego (the
parser the corpus build uses), which matches the `*` and `$` of RFC 9309; Python's
`RobotFileParser` ignores them, so a rule such as pap.pl's `Disallow: /aktualnosci/index*` did not
apply before. A robots.txt answering 429, 5xx or not at all means we do not fetch. Following RFC
9309 (2.3.1.3), a robots.txt answering any other 4xx, 401 and 403 included, is unavailable and
sets no rules (`RobotFileParser.read()` would treat 401 and 403 as "disallow everything"). The
page itself must still answer 200: we never get around a 401, 403, 429 or a bot challenge, and never retry with
another user agent. HTML is read with trafilatura, PDF with the link input's pypdf worker
(`prawdowid/extract_worker.py`, a child process with page and memory ceilings); both stop at the
same 2 MB cap and the same 8 s per page (`PAGE_BUDGET_S`).

### Search snippets of pages we cannot read (#95)

When our own fetch cannot use an allowlisted page (the site answers 403, 429 or another 4xx, a
5xx or nothing after the retry, its robots.txt cannot be read, it is slower than 8 s, over 2 MB,
of another type, or has no readable text), the hit stays as evidence built only from what the search API returned for it: Tavily's
title and `content` (up to three passages of about 500 characters copied from the page, joined by
`[...]`, per the [search API docs](https://docs.tavily.com/documentation/api-reference/endpoint/search),
read 2026-11-22), with the type and publisher from the allowlist, the provider's
`published_date` or none, and the time of the search as `fetched_at`. Tavily calls that date its
best estimate of when the page was published or last updated, so for a snippet it can be later
than the original publication. Rules:

- Nothing more is fetched for such a page: no retry, no other user agent, no proxy, and not
  Tavily's `raw_content` (the full page through a third party would be getting around the block).
- It is never saved, in the JSONL cache or in the database (`cache.store_document` refuses it).
- Quotes are checked against the snippet like against any fragment, and the source is marked
  `snippet_only` with the reason all the way to the answer: web and Discord show "fragment z
  wyników wyszukiwarki; <reason>", premises and the justification say so, and the verdict lists
  it as a limitation.
- It counts for the side it supports like a fetched page of the same type (a fact-checker's
  snippet can decide alone), but never makes the evidence "silna": that needs a reliable source we
  read ourselves and that carries a date.
- No snippet either for a page that robots.txt disallows (the site opted out of crawlers, so we
  do not use a search engine's copy), that is gone (404, 410), that redirects off the allowlist,
  or that sits behind a login or payment wall (401, 402): its content is not public, and the brief
  rules out paid databases.

This uses only what the search API returns. Michał approved the rule on 2026-11-22 (`WORKLOG.md`,
Decisions).

Our own database (step 2c: local PostgreSQL, tables `documents` and `chunks`,
schema in `db/migrations/`, compose service `sourcedb`, profile `sourcedb`, volume `sourcedb_data`) is **disabled in the pipeline** until the team
chooses licensed sources: checks never read or write it. It starts empty; only the seed script
writes to it (`make db-seed`, queries in `corpus/queries.txt`). Neither store is in the repo and we
do not redistribute page content. Controls on the database:

- Only pages found by the seed's web search are stored, never pages from links users submit.
- Licence per document (`licence`, taken from the approved-source allowlist for database seeds).
- Retention: `delete_after` defaults to 90 days after the page was stored (UNCONFIRMED: the team
  has not set the period; #17). `select delete_expired_documents()` deletes expired pages and their
  chunks; the seed script runs it first.
- Access: the database is reachable only on the compose network and on 127.0.0.1; no service is
  given its URI, only the seed script on the host. (`compose.prod.yaml` gives the backend a
  `DATABASE_URL` for production's separate `db`; nothing in a check reads it while 2c is disabled.)
- Deletion: `delete from documents where doc_id = '<canonical url>'` removes one page and its
  chunks. To delete only the local source store, run `docker compose -f compose.yaml --profile sourcedb rm -sf sourcedb`,
  then `docker volume rm <project>_sourcedb_data` (replace `<project>` with the Compose project name).
  This leaves production's separate `db` and `db_data` intact. Delete
  `corpus/docs.jsonl` to clear the local cache.
- No copies: page text from the database is never exported. The seed writes only metadata to
  `corpus/manifest.jsonl` (no text), so retention and deletion in the database cover every stored
  copy. A citation eval against database content needs an export that follows the same retention;
  it is left for when step 2c is enabled.
- Seed settings: `make db-seed` reads `.env` like the app does and builds the URI from
  `POSTGRES_PASSWORD` and `DB_PORT` (a `DATABASE_URL` you set wins).

Where the data is processed: on the machine that runs the compose stack.

## Full-text seed approval

`make db-seed` currently refuses: **no sources are approved**. Before adding an entry to
`APPROVED_SOURCES` in `prawdowid/corpus.py`, the team must record the legal basis, confirmed licence
and terms link, agreed retention period, access rules and deletion procedure here. Each entry maps
an exact hostname to its confirmed full-text licence; subdomains need their own approval.
The seed searches only approved hosts and checks each final page URL again after redirects before
storing it. Empty or UNCONFIRMED licences do not permit storage. The metadata manifest records the
approved licence. The search relevance allowlist below does not grant permission to archive pages.

Licences: **UNCONFIRMED for every domain.** Nobody on the team has checked each site's terms yet.
The column says where to check. Until it is checked we quote short passages with a link, and do not
republish pages.

## Primary and official sources (`official`)

| Domain | Publisher | Why it qualifies | Licence (check) |
|---|---|---|---|
| `gov.pl` | the office named on the page | `.gov.pl` is reserved for public administration bodies (citation for the registry rule UNCONFIRMED) | each service's terms page, UNCONFIRMED |
| `sejm.gov.pl` | Kancelaria Sejmu | parliament, Sejm prints, ISAP legal acts database | sejm.gov.pl terms, UNCONFIRMED |
| `stat.gov.pl` | Główny Urząd Statystyczny | official statistics | stat.gov.pl terms, UNCONFIRMED |
| `pkw.gov.pl` | Państwowa Komisja Wyborcza | official election results and rules | UNCONFIRMED |
| `prezydent.pl` | Kancelaria Prezydenta RP | statements and acts of the President | UNCONFIRMED |
| `nbp.pl` | Narodowy Bank Polski | central bank data and reports | UNCONFIRMED |
| `europa.eu` | the EU institution named on the page | official EU institutions (Commission, Council, Parliament) | europa.eu legal notice, UNCONFIRMED |
| `eur-lex.europa.eu` | EUR-Lex, Urząd Publikacji UE | official EU law | EUR-Lex legal notice, UNCONFIRMED |
| `nato.int` | NATO | official NATO statements | UNCONFIRMED |
| `who.int` | Światowa Organizacja Zdrowia | official health data | UNCONFIRMED |

## Known-narrative database (`disinfo_database`)

An official EU body, but a match only says that a claim resembles a documented pro-Kremlin
narrative. It is context: the verdict rules never count it as a reliable source on its own.

| Domain | Publisher | Why it qualifies | Licence (check) |
|---|---|---|---|
| `euvsdisinfo.eu` | EUvsDisinfo (ESDZ) | EEAS East StratCom Task Force disinformation cases | UNCONFIRMED |

## Reliable secondary sources (`fact_check`, `news`) and media (`media`)

| Domain | Publisher | Type | Why it qualifies | Licence (check) |
|---|---|---|---|---|
| `konkret24.tvn24.pl` | Konkret24 | `fact_check` | fact-checking desk of TVN24; membership UNCONFIRMED | UNCONFIRMED |
| `fakenews.pl` | FakeNews.pl | `fact_check` | Polish fact-checker; membership UNCONFIRMED | UNCONFIRMED |
| `sprawdzam.afp.com` | AFP Sprawdzam | `fact_check` | AFP's Polish fact-checking service; membership UNCONFIRMED | UNCONFIRMED |
| `demagog.org.pl` | Demagog | `fact_check` | Polish fact-checker; EFCSN verified member until 2027-05-25 (`corpus/catalog.yaml`, read 2026-11-21) | UNCONFIRMED; robots.txt `Content-Signal: search=yes,ai-train=no,use=reference`, `ai-input` not set (read 2026-11-22 from a home IP) |
| `pravda.org.pl` | Stowarzyszenie Pravda | `fact_check` | Polish fact-checker; EFCSN verified member until 2028-02-23 (`corpus/catalog.yaml`) | no licence on the site (corpus catalogue, 2026-11-21): short quote and link only |
| `oko.press` | OKO.press | `media` | news site with a fact-check section (`/kategoria/prawda-czy-falsz`); its articles have flat URLs, so the section cannot be told apart and the whole site is `media`: one publisher like any other, not a reliable type and not `news` (a news agency's own finding can stand against a reliable source in `judge.decide`) | UNCONFIRMED |
| `pap.pl` | Polska Agencja Prasowa | `news` | national news agency | UNCONFIRMED |

Reachability from our server (OVHcloud VPS, measured 2026-11-22 00:50 CET, our user agent and a
browser one): `konkret24.tvn24.pl`, `sprawdzam.afp.com` and `demagog.org.pl` (Cloudflare) answer
403 to every request, robots.txt included, so only their search snippets reach the judge;
`oko.press` and `pravda.org.pl` answer 200. From a home IP konkret24's robots.txt allows bots on its articles (GPTBot is kept off the whole
site; every bot only off `/_e/p/playlist/*` and `*?page=*`), so this is an IP-level block, not
an opt-out. AFP's robots.txt answers 403 from a home IP too
(Akamai, 2026-11-22), so its crawler policy could not be read; its terms restrict automated
extraction (`docs/submission/sources.md`). Demagog is on the list (#76) because the Fact Check
Tools integration only matches phrases literally, so its reviews often do not show up there (the
mentor on Discord, 21.11, 22:54).

A domain's type is a property of the source, shown next to it. It never decides whether a claim is
true.

## Updating

Add or remove a domain in `ALLOWLIST` and in this file in the same commit, then rebuild the corpus.
Membership of the fact-checkers should be checked on the IFCN signatories list and the EFCSN members
list before submission.
