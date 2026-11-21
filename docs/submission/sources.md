# Sources, qualification and update policy

This inventory describes code on `main` (after the issue11-fanout/judge/source-store stack merged
into it), not a populated or licensed corpus.
`UNCONFIRMED` means that access, a permission or a document-level licence has not been established.
A public page, an allowlist entry and a robots.txt permission do not themselves authorise
archiving. The runtime does not enforce licence approval before caching fetched pages.

## Retrieval services and the own store

| Source | What the code uses and how it qualifies | Terms / licence and remaining checks | Update behaviour |
|---|---|---|---|
| Google Fact Check Tools | `claims:search`, with Polish language filter by default. Valid review URLs become `fact_check` candidates, with publisher, review date when present and retrieval time. Ratings are not verdicts; the review title can be the only available evidence text. There is no publisher allowlist for Google results. Demagog's ratings reach the service only this way, as ClaimReview records; there is no direct Demagog integration. [factcheck.py](../../prawdowid/factcheck.py) | [Google API terms](https://developers.google.com/terms/); [endpoint documentation](https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search). Rights to each publisher's review remain separate and UNCONFIRMED until checked. Google documentation licensing does not license the returned articles. | Queries run per checked claim when a key exists. Google's index freshness and review correction timing are UNCONFIRMED; no local refresh schedule. |
| Tavily web search (`/search`) | Official `/search` endpoint through `tavily-python`, with `include_domains`/`include_domains_mode="restrict"` enforcing the allowlist server-side, `language="pl"` and `include_published_date=True` (`Document.published_at` falls back to it). Replaced DuckDuckGo (#7/#45): 7 of 8 quick-eval cases now get at least one allowlisted web source (was 0 of 8), measured on a live-`TAVILY_API_KEY` smoke run before the Tavily branch merged onto `main` — not the same run as the committed `latest.json` (see the "#7/#8 live proof" entry in [WORKLOG.md](../../WORKLOG.md)). Search hits only locate pages; the fetched page, not the search snippet, supplies evidence. See the complete domain inventory below. [websearch.py](../../prawdowid/websearch.py) | Official, signed-up API, not scraping. [Tavily API terms](https://docs.tavily.com/documentation/api-credits) describe the free tier (1,000 credits/month, 1 credit per basic search). [Data retention](https://help.tavily.com/articles/6781493822-data-retention) states GDPR and SOC 2; EU data residency and whether Nebius's pending acquisition of Tavily changed processing location are UNCONFIRMED. Publisher terms of fetched pages still apply (allowlisting is not consent). | Searches run per query, 1 credit each (observed ~4.9 credits/check on the 8-case quick eval). Pages are fetched live. The JSONL cache replaces the stored copy for an already-seen URL and keeps it for 30 days ([cache.py](../../prawdowid/cache.py)). |
| EUvsDisinfo MCP | Fixed `search` tool over cases and analytical articles. Accepts links only on `euvsdisinfo.eu` or its subdomains. Uses `disinfo_database`, context about documented pro-Kremlin narratives, not sufficient evidence on its own. The adapter records retrieval time and leaves publication date unknown. [euvsdisinfo.py](../../prawdowid/euvsdisinfo.py), [judge.py](../../prawdowid/judge.py) | [EEAS legal notice](https://www.eeas.europa.eu/eeas/legal-notice_en?s=228) describes attribution and exceptions; its applicability to each MCP result and MCP-specific reuse terms are UNCONFIRMED. [EUvsDisinfo access page](https://euvsdisinfo.eu/about/) says access is by request. Successful authenticated use on `main` is UNCONFIRMED; [WORKLOG](../../WORKLOG.md) records no live authorised search. | A lookup runs per checked claim when a key exists. No local MCP archive or refresh job. Upstream update cadence is UNCONFIRMED. |
| Own PostgreSQL source store; issue name includes Supabase | Local PostgreSQL in an opt-in Compose profile, not Supabase hosting. Tables contain fetched pages, licence metadata and text chunks, searched with PostgreSQL full-text search. It is disabled in `pipeline._retrieve`; only the seed writes to it. No seeded corpus is demonstrated. [cache.py](../../prawdowid/cache.py), [compose.yaml](../../compose.yaml), [migration](../../db/migrations/001_source_store.sql) | [PostgreSQL software licence](https://www.postgresql.org/about/licence/) covers the database software, not stored content. Per-document permissions are UNCONFIRMED; the schema's `licence` column is `not null` ([migration:20](../../db/migrations/001_source_store.sql#L20)) and the app refuses to insert a page without one ([cache.py:323](../../prawdowid/cache.py#L323)), so the gate is enforced, not just metadata — it still depends on the team actually confirming each domain's terms first. [Supabase terms](https://supabase.com/terms) are for a possible hosted deployment, not an active source on `main`. | Manual `make db-seed`, after licensing decisions. Canonical URLs are inserted once; no content-refresh upsert. Expired documents and dependent chunks are deleted when the seed starts; no scheduled deletion. [corpus.py](../../prawdowid/corpus.py), [cache.py](../../prawdowid/cache.py) |

User-submitted links are input material, not an additional evidence collection. Public HTTP(S)
HTML/PDF is fetched with address and access checks; the linked URL is excluded from evidence for
its own claims. Input pages are not saved by this path. Their individual terms and users' rights
to submit them are UNCONFIRMED ([link.py](../../prawdowid/link.py),
[verifier.py](../../prawdowid/verifier.py), [rerank.py](../../prawdowid/rerank.py)).

## Complete web evidence allowlist

The entries and type labels below come from `ALLOWLIST` in
[prawdowid/websearch.py](../../prawdowid/websearch.py). Host matching checks the closest parent;
for example an unlisted public-office subdomain can match `gov.pl`. These labels express the
team's source policy, not an independent audit. Fact-checker certification is UNCONFIRMED and is
not used as a runtime gate. Google can return review publishers outside this list.

All entries share this update path: live search and fetch, publication date extraction and
retrieval timestamp, then the local cache replaces the record for that URL on every save. No per-domain
refresh schedule exists. A fetched web page must have text, title and a parseable publication
date; access errors, non-HTML, robots disallow and off-list redirects are skipped. The date
extractor may infer a date from page text, so its accuracy is UNCONFIRMED. Undated Google and
MCP candidates can still enter the judge with a limitation. Sources:
[websearch.py](../../prawdowid/websearch.py), [factcheck.py](../../prawdowid/factcheck.py),
[euvsdisinfo.py](../../prawdowid/euvsdisinfo.py), [judge.py](../../prawdowid/judge.py).

| Domain | Code publisher / type and why selected | Licence or terms link; status for this use |
|---|---|---|
| `gov.pl` | Publisher from page metadata; `official`. Public administration statements and documents. | [Gov.pl copyright](https://www.gov.pl/web/gov/prawa-autorskie): text licence and exceptions are stated there. A blanket permission for all subdomains and third-party material is UNCONFIRMED. |
| `sejm.gov.pl` | Kancelaria Sejmu; `official`. Parliamentary documents and legislative records. | [Sejm copyright notice](https://www.sejm.gov.pl/projekt2.htm): non-commercial reuse with source attribution, reserved material excluded. Document-level scope and application to this cache are UNCONFIRMED. |
| `stat.gov.pl` | Główny Urząd Statystyczny; `official`. Published statistical data. | [GUS public-information reuse terms](https://bip.stat.gov.pl/kontakt/ponowne-wykorzystywanie-informacji-sektora-publicznego/?pdf=1). Application to selected pages and cache is UNCONFIRMED. |
| `pkw.gov.pl` | Państwowa Komisja Wyborcza; `official`. Election results and rules. | Publisher-specific reuse terms UNCONFIRMED; no confirmed licence page found. [Official public-information reuse guidance](https://www.gov.pl/web/gov/wykorzystaj-informacje-sektora-publicznego2) is a terms-checking reference, not a licence from PKW. |
| `prezydent.pl` | Kancelaria Prezydenta RP; `official`. Presidential statements and acts. | [KPRP reuse conditions](https://www.prezydent.pl/kancelaria/ponowne-wykorzystywanie-informacji-sektora-publicznego). Permission for each chosen page and this cache is UNCONFIRMED. |
| `nbp.pl` | Narodowy Bank Polski; `official`. Central-bank data and reports. | Publisher-specific reuse terms UNCONFIRMED; the site blocked inspection. [Official public-information reuse guidance](https://www.gov.pl/web/gov/wykorzystaj-informacje-sektora-publicznego2) is a terms-checking reference, not an NBP licence. |
| `europa.eu` | Publisher from page metadata; `official`. EU institution documents. | [EU portal legal notice](https://european-union.europa.eu/legal-notice_en). This notice covers that portal, not every institution or subdomain; document-specific permissions remain UNCONFIRMED. |
| `eur-lex.europa.eu` | EUR-Lex, Urząd Publikacji UE; `official`. EU law and related documents. | [EUR-Lex legal notice](https://eur-lex.europa.eu/content/legal-notice/legal-notice.html?locale=en): reuse and attribution, with document exceptions. Each document and this use require confirmation: UNCONFIRMED. |
| `euvsdisinfo.eu` | EUvsDisinfo (ESDZ); `disinfo_database`. Known-narrative context. | [EEAS legal notice](https://www.eeas.europa.eu/eeas/legal-notice_en?s=228); applicability to individual site/MCP content UNCONFIRMED. See MCP access conditions above. |
| `nato.int` | NATO; `official`. NATO statements and institutional documents. | [NATO content terms](https://www.nato.int/en/about-us/official-texts-and-resources/use-of-nato-content-and-brand). Crediting and other restrictions apply; archiving permission for this use UNCONFIRMED. |
| `who.int` | Światowa Organizacja Zdrowia; `official`. Public-health publications. | [WHO website terms](https://www.who.int/about/policies/terms-of-use), [publication licensing](https://www.who.int/about/policies/publishing/copyright). Website extracts and individual publications have different conditions; this cache's permission is UNCONFIRMED. |
| `konkret24.tvn24.pl` | Konkret24; `fact_check`. TVN24 fact-checking desk. | [Published Konkret24 terms](https://n-22-4.dcs.redcdn.pl/file/o2/tvn/web-content/m/p187/f/57c0531e13f40b91b3b0f1a30b529a1d/9b90f4fc-9e98-4586-829f-ae3d8c2389a3.pdf). Current applicability and permission for automated storage UNCONFIRMED; the linked terms restrict use to private purposes. |
| `fakenews.pl` | FakeNews.pl; `fact_check`. Polish fact-checking articles. | [Publisher's terms page](https://fakenews.pl/regulamin/). Its body did not expose usable reuse conditions during inspection; licence and cache permission UNCONFIRMED. |
| `sprawdzam.afp.com` | AFP Sprawdzam; `fact_check`. AFP's Polish fact-checking service. | [AFP terms](https://www.afp.com/en/useful-links/terms-use) explicitly include this domain and restrict automated extraction/archiving without consent, subject to stated exceptions. Project permission UNCONFIRMED; allowlisting is not consent. |
| `pap.pl` | Polska Agencja Prasowa; `news`. News-agency reporting. | [PAP terms](https://www.pap.pl/regulamin) reserve text/data mining and require consent beyond permitted private use. Project permission UNCONFIRMED; do not treat the allowlist as clearance. |

The policy links were inspected for this draft. They are references for the team's outstanding
licensing decision, not a certification that this implementation complies with each policy.
No restricted pages were fetched to build a corpus for this task.

## Storage, freshness and deletion limits

The [existing source register](../sources.md) and [WORKLOG](../../WORKLOG.md) record that the
demo corpus has not been built. The tracked [seed queries](../../corpus/queries.txt) are not a
document corpus. A populated manifest, licensed source list and citation corpus remain open.

The own-store expiry defaults to `30 days` (`RETENTION_DAYS`, `prawdowid/privacy.py`), set by the
app itself on every insert
([cache.py:314,328](../../prawdowid/cache.py#L314)); the column's own default at
[db/migrations/001_source_store.sql:27](../../db/migrations/001_source_store.sql#L27) only covers
a manual insert that does not pass it explicitly. That is an implemented default, not a confirmed
team retention policy. The seed's own-store insert keeps the first-stored copy of a document id,
`on conflict (doc_id) do nothing`, and does not refresh already stored canonical URLs
([cache.py:315](../../prawdowid/cache.py#L315)). The separate JSONL web cache instead
replaces the stored record for that URL on every save and drops anything older than
`RETENTION_DAYS` (30 days) on each save
([cache.py:141](../../prawdowid/cache.py#L141), [:150](../../prawdowid/cache.py#L150)), and keeps
extracted text only for a document with a confirmed licence
([cache.py:164,167](../../prawdowid/cache.py#L164)).

To remove one database document, an operator deletes its row by `doc_id`; chunks cascade.
Clearing `pgdata` destroys the whole source database. Removing `corpus/docs.jsonl` clears the
separate web cache. A user-facing session deletion now exists for the check log (#17, #39):
`DELETE /api/sessions/{id}` and a "Usuń moje sprawdzenia" button on the web page remove every
record of one session from `prawdowid/checklog.py`; see [docs/privacy.md](../privacy.md). It does
not cover the JSONL web cache or the source store, and stdout logs have no deletion or retention
beyond process lifetime. Source material is processed on the deployment host and may be sent to
Anthropic for ranking and judgement; provider-side retention is UNCONFIRMED.

Before seeding or enabling the store, the team must confirm rights for each document, set a
retention policy and decide which domains remain eligible. Changes to `ALLOWLIST` also require
updating [docs/sources.md](../sources.md); the existing test checks that register. No source
policy or product code is changed by these submission drafts.
