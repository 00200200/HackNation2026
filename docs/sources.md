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

What we store: web search saves the extracted text of every fetched page to the local cache
`corpus/docs.jsonl`. Our own database (step 2c: local PostgreSQL, tables `documents` and `chunks`,
schema in `db/migrations/`, compose service `db`) is **disabled in the pipeline** until the team
chooses licensed sources: checks never read or write it. It starts empty; only the seed script
writes to it (`make db-seed`, queries in `corpus/queries.txt`). Neither store is in the repo and we
do not redistribute page content. Controls on the database:

- Only pages found by the seed's web search are stored, never pages from links users submit.
- Licence per document (`licence`, UNCONFIRMED until checked, see below).
- Retention: `delete_after` defaults to 90 days after the page was stored (UNCONFIRMED: the team
  has not set the period; #17). `select delete_expired_documents()` deletes expired pages and their
  chunks; the seed script runs it first.
- Access: the database is reachable only on the compose network and on 127.0.0.1; no service is
  given `DATABASE_URL`, only the seed script on the host.
- Deletion: `delete from documents where doc_id = '<canonical url>'` removes one page and its
  chunks. `docker compose --profile db down -v` deletes the whole database volume. Delete
  `corpus/docs.jsonl` to clear the local cache. After a seed, the database export for
  `evals.run --corpus` is `corpus/db-export.jsonl`.

Where the data is processed: on the machine that runs the compose stack.

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
