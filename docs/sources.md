# Source list

Web search (step 2b, `prawdowid/websearch.py`) only returns pages from the domains below. A host
matches its own entry or the closest parent entry (`nik.gov.pl` falls under `gov.pl`). The list
lives in `ALLOWLIST`; `tests/test_websearch.py` fails when a domain there is missing here.

Every cached document has a title, publisher, publication date (`published_at`, found by
trafilatura/htmldate, mostly in page metadata; on a page without date metadata it can come from a
date written on the page, so it may be wrong there; pages with no date are skipped) and retrieval time (`fetched_at`). The per-document list
goes to `corpus/manifest.jsonl` when the corpus is built with `uv run python -m prawdowid.corpus`.
**The corpus is not built yet:** DuckDuckGo returned no results from our machine on 2026-11-21, and
the team will replace the provider (#7, #8).

What we store (`prawdowid/cache.py`): metadata of every page (URL, title, publisher, dates,
type, domain, licence) in the local file `corpus/docs.jsonl`, owner-only (0600), not in the repo.
Full page text is stored only for a domain whose licence is confirmed (`licence` in `ALLOWLIST`);
today none is, so no page text is archived. The pipeline uses the live text in memory for the
current check only. Records older than 30 days (`RETENTION_DAYS`, by `fetched_at`) are never loaded
and are dropped on every save, a new fetch of the same URL replaces the old record, `delete_document(url)` deletes one
record and deleting the file deletes all. Until licences are confirmed the cache cannot serve as
the eval corpus for citation correctness, which needs the text.

How pages are fetched (`prawdowid/safefetch.py`): every hop, redirects included, must be on the
allowlist, use http(s) on the default port, resolve only to public IP addresses (the connection
goes to the checked address) and be allowed by that host's robots.txt. A robots.txt answering 429,
5xx or not at all means we do not fetch. We never get around a 401, 403, 429 or a bot challenge.

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
| `euvsdisinfo.eu` | EUvsDisinfo (ESDZ) | EEAS East StratCom Task Force disinformation cases | UNCONFIRMED |
| `nato.int` | NATO | official NATO statements | UNCONFIRMED |
| `who.int` | Światowa Organizacja Zdrowia | official health data | UNCONFIRMED |

## Reliable secondary sources (`fact_check`, `news`)

| Domain | Publisher | Type | Why it qualifies | Licence (check) |
|---|---|---|---|---|
| `demagog.org.pl` | Demagog | `fact_check` | Polish fact-checker; IFCN or EFCSN membership UNCONFIRMED | UNCONFIRMED |
| `konkret24.tvn24.pl` | Konkret24 | `fact_check` | fact-checking desk of TVN24; membership UNCONFIRMED | UNCONFIRMED |
| `fakenews.pl` | FakeNews.pl | `fact_check` | Polish fact-checker; membership UNCONFIRMED | UNCONFIRMED |
| `sprawdzam.afp.com` | AFP Sprawdzam | `fact_check` | AFP's Polish fact-checking service; membership UNCONFIRMED | UNCONFIRMED |
| `pap.pl` | Polska Agencja Prasowa | `news` | national news agency | UNCONFIRMED |

A domain's type is a property of the source, shown next to it. It never decides whether a claim is
true.

## Updating

Add or remove a domain in `ALLOWLIST` and in this file in the same commit, then rebuild the corpus.
Membership of the fact-checkers should be checked on the IFCN signatories list and the EFCSN members
list before submission.
