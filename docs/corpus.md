# Sources of faktczyfejk.pl

The verifier answers only from evidence it can cite. That evidence comes from a fixed, published
set of sources: official Polish and EU publications and fact-checkers with a current IFCN or EFCSN
status. This page describes them, their licences, how we admit, update and exclude them, and how
the corpus is rebuilt.

- Source list with every decision: [`corpus/catalog.yaml`](../corpus/catalog.yaml)
- Corpus: [`corpus/evidence.jsonl`](../corpus/evidence.jsonl), one JSON record per line
- Last build, per source, with the reason for anything skipped: [`corpus/manifest.json`](../corpus/manifest.json)

## Rebuild and check

```bash
make corpus          # uv run python -m corpus.build: fetch every active source, write evidence.jsonl
make corpus-check    # uv run python -m corpus.check: counts and the brief's thresholds
```

Each site gets at most one request per second, so a first build takes about an hour (most of
it is the Demagog archive). Pages are cached in `corpus/.cache/` (not in git). A rebuild fetches
again every list, feed and API answer older than the source's update interval (1 hour for IMGW
warnings, 6 hours for Odyseusz, a day for news); article pages are reused until
`make corpus ARGS=--refresh`. `ARGS="--only odyseusz"` rebuilds one source and keeps the rest.
A source that fails, stops part way, returns nothing or misses its key keeps its records from the
previous build, and the manifest says so; IMGW warnings are the exception, because an old snapshot would
mislead. A build that misses a threshold writes nothing and exits with an error (`--force`
writes anyway).

## What is in the corpus

Build of 21.11.2026 (numbers from `make corpus-check`):

| Registered domain | Publisher | Type | Records | Stored |
|---|---|---|---:|---|
| www.gov.pl | RCB, MSZ, MSWiA, KG PSP, MON, GIS, MI, KPRM, PAA, MZ, MC, GDDKiA, Wody Polskie | official | 396 | full text |
| cert.pl | CERT Polska (NASK) | official | 284 | full text |
| odyseusz.gov.pl | MSZ travel information: 239 country profiles, 12 information pages | official | 251 | full text, cut at 8,000 characters |
| policja.pl | Komenda Główna Policji | official | 45 | full text |
| policja.gov.pl | KWP z siedzibą w Radomiu | official | 38 | full text |
| stat.gov.pl | Główny Urząd Statystyczny | official | 36 | full text |
| imgw.pl | IMGW-PIB, weather and hydrological warnings | official | 36 | full text |
| kgsok.pl | Komenda Główna Straży Ochrony Kolei | official | 30 | fragment |
| sejm.gov.pl | Dziennik Ustaw through the Sejm ELI API: 19 consolidated texts, 1 act | official | 20 | full text, cut at 30,000 characters |
| europa.eu | Official Journal of the EU through the Publications Office | official | 7 | full text, cut at 40,000 characters |
| demagog.org.pl | Stowarzyszenie Demagog: 900 statements (01.2024–11.2026), 900 fake-news checks (04.2025–11.2026), 30 analyses | fact-checker | 1,830 | claim, rating, justification fragment, cited links |
| pravda.org.pl | Stowarzyszenie Pravda | fact-checker | 15 | fragment |

2,988 records, 12 registered domains, two source types (1,143 official, 1,845 fact-checker), 8.6 MB.
The brief asks for at least 100 records, 10 domains and two types.

We count registered domains with the Public Suffix List, where `gov.pl` is a suffix. All pages of
www.gov.pl are one domain; sejm.gov.pl and odyseusz.gov.pl are separate domains. Counted strictly,
with every `*.gov.pl` name as one domain, the corpus has 8.

Each record has `id`, `url`, `title`, `publisher`, `published_at` (null when the page states no
date), `retrieved_at`, `source_type`, `licence`, `language` and `text`, plus `source_id` (the
catalogue entry), `storage` and `truncated`. Fact-check records also carry `claim` (the reviewed
claim, verbatim), `rating` (the fact-checker's label, verbatim as published, e.g. "Fałsz",
"Fałsz.", "Manipulacja", "Brakujący kontekst": normalise before comparing) and `cited_links` (the
links in the fact-checker's justification, URL and link text, without tracking parameters; links
to social platforms, post archives, the fact-checker's own site and domains on the
disinformation list are left out). For Demagog's statements of public figures they also carry
`claim_author` and `claim_source` (where the statement was first published). The `text` of a
fact-check is the rating, the claim (cut at 250 characters) and the start of the justification,
at most 500 characters in all.

## Admission, update and exclusion

The rules are in `corpus/catalog.yaml` under `rules`. In short:

- **Admit** official Polish and EU bodies, fact-checkers whose IFCN or EFCSN status we read on the
  network's own member page (the entry records the date), and the incident base named by the
  organiser. The terms must allow at least a fragment with a link, and the content must be reachable
  without going around robots.txt, a login, a paywall or bot protection.
- **Update** every active source with `make corpus`. Each entry has an interval (from 1 hour for
  IMGW warnings to 30 days for EU acts). Records keep their own publication and retrieval time, so
  the verifier can prefer recent material and flag old material as archival.
- **Exclude** a source when robots.txt disallows it, the site refuses scripted clients, it stays
  unreachable for longer than one interval, it loses its fact-checker status, or its terms stop
  allowing a fragment. Excluded entries stay in the catalogue with the reason and date. One document
  is removed by adding its URL to `removed_urls` with a reason and rebuilding.

Fact-checker status read on 21.11.2026: Demagog is an EFCSN verified member until 25.05.2027 and,
by its own statement, an IFCN signatory (IFCN's list could not be read by a script, so this part is
UNCONFIRMED). Pravda is an EFCSN verified member until 23.02.2028.

## Licences and what we store

We store full text only where a licence or the publisher's terms allow it. Otherwise we keep the
metadata, a fragment of at most 500 characters and the link, under the right of quotation
(art. 29 of the Polish copyright act). We store no images, audio or video.

| Source | Basis | Stored |
|---|---|---|
| gov.pl | Text published under CC BY-SA 4.0 (page footer) | full text |
| moje.cert.pl/komunikaty | CC BY-SA 4.0 unless stated otherwise (page footer) | full text |
| new.stat.gov.pl (GUS) | CC BY 4.0 (page footer) | full text |
| policja.pl, mazowiecka.policja.gov.pl | Site terms: reuse allowed with the source named | full text |
| Sejm ELI | Legal acts are not protected by copyright (art. 4 pt 1) | full text |
| EU Official Journal | Reuse allowed with the source named (EUR-Lex legal notice, Decision 2011/833/EU) | full text |
| IMGW-PIB | Data terms: free reuse with two required sentences (below) | full text |
| odyseusz.gov.pl | Official material of MSZ (art. 4 pt 2) and public sector information. The site states no licence; the organiser (MSZ) named it as a source to collect (mentor, 21.11.2026) | full text, cut at 8,000 characters |
| kgsok.pl, pravda.org.pl | No licence stated | fragment |
| demagog.org.pl | No licence; robots.txt `Content-Signal: search=yes, ai-train=no, use=reference` | claim, rating, fragment |

Duties for every screen that shows a quote: name the publisher, link the document and give its
licence (each record carries it). Text under CC BY-SA 4.0 that we adapt stays under CC BY-SA 4.0.
Answers that use IMGW data must show "Źródłem pochodzenia danych jest Instytut Meteorologii i
Gospodarki Wodnej – Państwowy Instytut Badawczy" and, because we reformat the records, "Dane
Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego zostały przetworzone".
The IMGW terms treat publication funded by advertising as commercial use; this service has no ads.

## How we fetch

- robots.txt is read for every site and followed by the RFC 9309 rules (Protego). When robots.txt
  cannot be read because of a server or network error, the site is not crawled.
- At most one request per second per registered domain, longer when robots.txt sets a crawl delay.
  Timeouts of 20 seconds and at most two retries.
- A generic User-Agent, `faktczyfejk-corpus/0.1`, with no personal data.
- A bot challenge, HTTP 403 or 429 stops the source for that build. We never work around it.
- Two portals are read through the JSON their own pages load: Odyseusz (a single-page app; the
  exception in the catalogue's exclusion rule) and the Publications Office's Cellar API for EU acts
  (the EUR-Lex website answers scripts with a challenge, the API does not).
- PAP (www.pap.pl) answers scripts with a bot challenge, so PAP dispatches are not fetched. When a
  Demagog fact-check links a dispatch, the link and its link text are in `cited_links`.

## Personal data, retention and deletion

- The corpus holds only material the publishers made public. Who made a claim is stored only for
  public statements of public figures (Demagog's statements section), never for posts of private
  people; social media links are left out of `cited_links`. Job adverts, which list contact
  persons, are skipped. E-mail addresses in texts are masked. `make corpus-check` fails on an
  e-mail address, a number that passes the PESEL checksum, a "contact persons" block, or a record
  from a domain on the disinformation list. Embassy contact lists and flags from Odyseusz are left
  out. Where publishers shorten names (for example "Michał O."), the text stays as they published
  it; whether to mask these too is a team decision (OPEN).
- Retention: a record lives until a rebuild no longer finds it or it is removed through
  `removed_urls`. The page cache in `corpus/.cache/` is local, never committed, and can be deleted
  at any time.
- Access: the corpus is a file in the repository; who can read or change it is decided by the
  repository's permissions. It contains no data from the people who use the service.
- Deletion on request: add the URL to `removed_urls` with the reason and date, run `make corpus`,
  commit. The record disappears from `evidence.jsonl` and from every index built from it.

## Sources that need a key

| Source | Variable | Without it |
|---|---|---|
| Google Fact Check Tools API (`claims:search`), reviews by the admitted fact-checkers | `GOOGLE_FACTCHECK_API_KEY` | skipped, noted in the manifest |
| EUvsDisinfo cases (organiser's MCP server) | `EUVSDISINFO_TOKEN` | skipped, noted in the manifest |

Put them in `.env`; `make corpus` reads it. Neither has been run against the live service yet, so
the first run must be checked by hand. With the EUvsDisinfo token the build also writes
`corpus/disinfo_domains.json`: the domains linked in the cases' `linksToDisinformation`, with the
number of cases. It feeds only the neutral warning of ADR 0001, section 5. A domain on that list is
never evidence and never decides a verdict.

## Not used, and why

On the organiser's list but not collected: `www.gov.pl/web/gov/ostrzezenia` (filled in by a script),
utk.gov.pl (robots.txt disallows all clients except Googlebot), ulc.gov.pl, drogi.gddkia.gov.pl and
sar.gov.pl (bot challenge on every page), monitoring.paa.gov.pl, meteo.imgw.pl, hydro.imgw.pl and
baltyk.imgw.pl (map apps; the IMGW warnings come from its API instead), portalpasazera.pl (timetable
app). Also excluded: FakeHunter (PAP), AFP Fact Check and EDMO (they refuse scripted clients),
Konkret24 (the footer reserves redistribution; fact-checker status not confirmed). NASK, the
maritime offices in Gdynia and Szczecin and OKO.press are listed as candidates with what is
missing. GIOŚ air quality is meant for a live lookup at check time, because a stored copy would be
out of date within the hour. Details and dates: `corpus/catalog.yaml`.

## Limits

- News sources cover the latest pages of each list, not the full archive. Demagog is collected
  from the first 15 pages of its statements and fake-news feeds. Older fact-checks need the
  Google Fact Check Tools API key (it returns Demagog's ClaimReview records) or a deeper build;
  the file must stay under the 10 MB push limit.
- IMGW warnings and Odyseusz notices change within hours. The stored copy is a snapshot with its
  retrieval time; for questions about the present the verifier should ask these services live. A
  build with `--only` keeps the other sources' records as they are, the IMGW snapshot included.
- Sejm acts: for each topic the newest consolidated text that has an HTML version, otherwise the
  act itself; amendments are skipped. Acts from 2025 on are PDF only, so a consolidated text can
  predate the latest amendment (its date is kept). Cut at 30,000 characters. EU acts are the text
  first published in the Official Journal, without later amendments.
- Odyseusz country records link to the JSON endpoint the portal uses, because the address of the
  rendered country page could not be confirmed without running the app.
