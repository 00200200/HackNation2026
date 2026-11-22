"""Step 2 lookup in the registers of law: Polish acts (Sejm ELI API, ISAP) and EU acts (CELLAR).

Only for claims the extraction model gave `legal_queries` (a law, regulation, directive, ban or
obligation). Each query is cut to word stems and searched in act titles:

- ELI: `GET https://api.sejm.gov.pl/eli/acts/search?title=<stems>` (Dziennik Ustaw, Monitor
  Polski). Keyless; the terms of the API are not stated (UNCONFIRMED). Normative acts are not
  protected by copyright (art. 4 of the Polish copyright act).
- CELLAR: `GET https://publications.europa.eu/webapi/rdf/sparql` with a full-text query on the
  Polish titles of EU legislation (CELEX sector 3). Keyless. The EUR-Lex legal notice puts its
  metadata under CC0 and its legal documents under Decision 2011/833/EU; it does not name CELLAR,
  so the CELLAR terms are UNCONFIRMED (`docs/sources.md`).

Each act becomes one Document whose text is a Polish sentence rendered in code from the record
(title, status, dates), so the judge quotes the register, not a model. The link is the human page
(ISAP, EUR-Lex). The best act in force of each register also gets the articles of its text that
share most words with the claim: Polish acts from the ELI text PDF (a consolidated text when the
register lists one as the act in force), EU acts from the EUR-Lex HTML of the newest consolidated
version (else the act as published). Bounded like gov.pl: timeout per call, one retry, one budget per register (a slow one never
drops the other's acts), robots.txt respected. A failure is a limitation, never a verdict; no act found is an answer, not a failure.
"""

import asyncio
import json
import logging
import os
import re
import weakref
from collections import OrderedDict
from datetime import UTC, date, datetime
from io import BytesIO
from urllib.parse import urlsplit

import httpx2
import lxml.html
import pypdf

from prawdowid import safefetch
from prawdowid.cache import Document
from prawdowid.privacy import mask_personal_data
from prawdowid.websearch import WebSearch

log = logging.getLogger("prawdowid")

ENABLED = os.getenv("PRAWDOWID_LEGAL", "1") != "0"
ELI_SEARCH = "https://api.sejm.gov.pl/eli/acts/search"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
# op.europa.eu serves the robots.txt that publications.europa.eu redirects to.
HOSTS = frozenset({"api.sejm.gov.pl", "publications.europa.eu", "op.europa.eu"})
ELI_TEXT = "https://api.sejm.gov.pl/eli/acts/{eli}/text.pdf"
# CELLAR content negotiation: the Polish XHTML of a CELEX number (one redirect to the file in
# live runs on 2026-11-22; a 300 Multiple Choices is not followed and leaves no text).
EU_TEXT = "https://publications.europa.eu/resource/celex/{celex}"
TEXT_HEADERS = {"Accept": "application/xhtml+xml, text/html", "Accept-Language": "pol"}
MAX_QUERIES = 2  # per claim, whatever the model wrote
FETCH = 20  # acts asked per query and register; registers give no relevance order
LIMIT = 3  # acts kept per register after ranking
TIMEOUT_S = (
    7  # per call; a cold CELLAR query took over 4 s. A retry gets what BUDGET_S leaves
)
ATTEMPTS = 2  # first call plus one retry
BUDGET_S = 10  # each register, every query and retry included
# Amendments and corrections rank after the act itself, and so does a consolidated text that is
# no longer in force.
SECONDARY = ("zmian", "zmienia", "sprostowanie")
IN_FORCE = "Status: obowiązujący."
MAX_BYTES = 500_000
# Act text: Kodeks wyborczy is a 1.5 MB, 150-page PDF read in about 3 s (~20 ms a page).
TEXT_BUDGET_S = 8  # each register's text, fetch and parse
TEXT_MAX_BYTES = 5_000_000
MAX_PDF_PAGES = 200  # about 4 s of parsing, inside TEXT_BUDGET_S
PARSED_KEPT = (
    8  # parsed texts kept per event loop, so claims about one act parse it once
)
MAX_PASSAGES = 5  # pieces kept per act; rerank and the judge pick among them
MIN_HITS = 2  # claim stems an article must hold
MAX_PASSAGE_CHARS = 1500
PASSAGE_STEM_CHARS = 6  # looser than title stems: "komisjach" meets "komisji"
# The start of an article: "Art. 32." in Polish acts, "Artykuł 3" in EU acts.
ARTICLE = re.compile(r"(?=\b(?:Art\. \d+[a-z]*\.|Artykuł \d+[a-z]*\s))")
MAX_STEMS = 4
STEM_CHARS = 7  # Polish inflection: "cudzoziemców" is found by "cudzozi"
# Words of every act title, they narrow nothing.
GENERIC = {"ustawa", "ustawy", "ustawie", "ustawę", "rozporządzenie", "rozporządzenia"}
GENERIC |= {"dyrektywa", "dyrektywy", "decyzja", "decyzji", "sprawie", "zmianie"}
GENERIC |= {"przez", "oraz", "które", "których", "można", "jest", "może"}

ELI_UNAVAILABLE = (
    "Rejestr aktów prawnych Sejmu (ISAP) nie odpowiedział, "
    "więc nie sprawdziliśmy polskich przepisów."
)
EU_UNAVAILABLE = "EUR-Lex nie odpowiedział, więc nie sprawdziliśmy przepisów UE."
LOOKUP_UNAVAILABLE = (
    "Rejestry aktów prawnych (ISAP Sejmu, EUR-Lex) nie odpowiedziały, "
    "więc nie sprawdziliśmy treści ani statusu przepisów."
)

# Title stems; acts of Parliament and Council first, amendments and corrections last, newest
# first within each; one row per act (an act may have several entry-into-force dates).
EU_QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex (SAMPLE(?t) AS ?title) (MAX(?d) AS ?date) (SAMPLE(?f) AS ?force)
       (MIN(?e) AS ?eif) (MAX(?cc) AS ?cons) WHERE {{
 ?expr cdm:expression_title ?t ;
       cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/POL> ;
       cdm:expression_belongs_to_work ?work .
 ?t bif:contains "{terms}" .
 ?work cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?d .
 FILTER(STRSTARTS(STR(?celex), "3"))
 OPTIONAL {{ ?work cdm:resource_legal_in-force ?f }}
 OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?e }}
 OPTIONAL {{ ?c cdm:act_consolidated_based_on_resource_legal ?work ;
              cdm:resource_legal_id_celex ?cc }}
 BIND(IF(REGEX(?t, "zmian|zmienia|^Sprostowanie", "i"), 2,
         IF(REGEX(?t, "^(Rozporządzenie|Dyrektywa|Decyzja).{{1,3}}(Parlamentu|Rady)"), 0, 1))
      AS ?s)
}} GROUP BY ?celex ORDER BY ASC(MAX(?s)) DESC(MAX(?d)) LIMIT {limit}"""


def stems(
    query: str, chars: int = STEM_CHARS, limit: int | None = MAX_STEMS
) -> list[str]:
    """Words of a query cut to `chars`; short and generic words dropped."""
    words = re.findall(r"\w+", query.casefold())
    picked = [w[:chars] for w in words if len(w) >= 4 and w not in GENERIC]
    return list(dict.fromkeys(picked))[:limit]


def passages(text: str, claim: str) -> list[str]:
    """The pieces of an act's text holding the claim's stems, rare stems weighing more (a stem
    in one piece counts 1, in ten pieces 0.1), in the act's order. A piece is an article, or a
    part of a long one led by its number."""
    want = stems(claim, PASSAGE_STEM_CHARS, None)
    # Words split across PDF lines; non-breaking spaces of EU texts ("Artykuł\xa01").
    text = re.sub(r"-\n", "", text).replace("\xa0", " ")
    articles = [" ".join(p.split()) for p in ARTICLE.split(text)]
    # The part before the first article is the preamble or the notice's header.
    parts = [c for a in articles[1:] or articles for c in _pieces(a)]
    held = [{w for w in want if w in p.casefold()} for p in parts]
    seen = {w: sum(w in h for h in held) for w in want}
    scored = [
        (sum(_weight(w) / seen[w] for w in h), i)
        for i, h in enumerate(held)
        if len(h) >= MIN_HITS
    ]
    best = sorted(scored, key=lambda s: (-s[0], s[1]))[:MAX_PASSAGES]
    return [parts[i] for _, i in sorted(best, key=lambda s: s[1])]


def _weight(stem: str) -> int:
    # ponytail: a number in the claim (a year, an amount) is its checkable core, so it counts
    # five times; tune on eval cases if pieces with the number keep losing to wordy ones.
    return 5 if stem.isdigit() else 1


def _pieces(article: str) -> list[str]:
    """An article cut at sentence ends into pieces of up to MAX_PASSAGE_CHARS."""
    if len(article) <= MAX_PASSAGE_CHARS:
        return [article]
    head = article.split(" ", 2)[:2]  # "Art. 32." / "Artykuł 1"
    pieces, piece = [], ""
    # Not after "r." of a date ("1 stycznia 2035 r.") or a number ("§ 2.", "Art. 7."), which end
    # no sentence.
    for sentence in re.split(r"(?<=[.;:])(?<! r\.)(?<!\d\.)\s+", article):
        if piece and len(piece) + len(sentence) > MAX_PASSAGE_CHARS:
            pieces.append(piece.strip())
            piece = " ".join(head) + " (…) "
        piece += sentence + " "
    pieces.append(piece.strip())
    return [p[:MAX_PASSAGE_CHARS] for p in pieces]


async def search_legal(
    queries: list[str],
    claim: str = "",
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> WebSearch:
    """Polish and EU acts whose titles hold each query's stems; the best act in force of each
    register with the articles of its text closest to `claim`. `transport` is for tests."""
    terms = [s for s in (stems(mask_personal_data(q)) for q in queries) if s]
    terms = terms[:MAX_QUERIES]
    if not terms:
        return WebSearch()
    async with safefetch.client(TIMEOUT_S, transport) as http:
        pl, eu = await asyncio.gather(
            _register(_eli, terms, http), _register(_eu, terms, http)
        )
        if pl is None and eu is None:
            return WebSearch(limitation=LOOKUP_UNAVAILABLE)
        if claim:
            await asyncio.gather(_add_text(pl, claim, http), _add_text(eu, claim, http))
    docs = list({a[0].url: a[0] for a in [*(pl or []), *(eu or [])]}.values())
    failed = ELI_UNAVAILABLE if pl is None else EU_UNAVAILABLE if eu is None else None
    return WebSearch(documents=docs, limitation=failed)


# An act, the URL of its text (None when not read: not in force, no text) and the version that
# text is, e.g. "Dz.U. 2026 poz. 1261, tekst ogłoszony 2026-09-28".
Act = tuple[Document, str | None, str]
_parsed: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


async def _register(search, terms: list[str], http) -> list[Act] | None:
    """One register's best acts for all queries; None when it failed or ran over BUDGET_S."""
    try:
        async with asyncio.timeout(BUDGET_S):
            results = await asyncio.gather(*(search(t, http) for t in terms))
    except TimeoutError:
        log.warning("legal %s over %g s", search.__name__, BUDGET_S)
        return None
    if all(r is None for r in results):
        return None
    acts = list({a[0].url: a for r in results if r for a in r}.values())
    # Stable sort: newest first within each group, as the register answered.
    acts.sort(key=lambda a: _secondary(a[0]))
    return acts[:LIMIT]


def _secondary(doc: Document) -> bool:
    title = doc.title.casefold()
    stale = "jednolitego tekstu" in title and IN_FORCE not in doc.text
    return stale or any(w in title for w in SECONDARY)


async def _add_text(acts: list[Act] | None, claim: str, http) -> None:
    """Articles of the text of the best-ranked act in force closest to the claim, added to its
    Document in place. A text that fails or runs over TEXT_BUDGET_S leaves the record as it was."""
    at = next((i for i, a in enumerate(acts or []) if a[1]), None)
    if at is None:
        return
    doc, url, version = acts[at]
    # Only CELLAR negotiates; the ELI PDF answers 406 to an XHTML Accept.
    headers = TEXT_HEADERS if url.startswith(EU_TEXT.split("{")[0]) else None
    try:
        async with asyncio.timeout(TEXT_BUDGET_S):
            page = await safefetch.get(
                url, http, allow=_allowed, max_bytes=TEXT_MAX_BYTES, headers=headers
            )
            if page.status != 200:
                log.warning("legal text %s: HTTP %d", url, page.status)
                return
            text = await _parse(url, page)
    except (TimeoutError, safefetch.Blocked, httpx2.HTTPError) as exc:
        log.warning("legal text %s skipped: %r", url, exc)
        return
    except Exception:  # a malformed PDF or HTML: the record still stands
        log.exception("legal text %s not readable", url)
        return
    found = passages(text, claim)
    if found:
        # Each passage becomes its own rerank fragment, so each names the version it is from:
        # later amendments not yet in a consolidated text are not in it.
        intro = f"Fragmenty tekstu ({version}; bez zmian późniejszych niż ten tekst):"
        found = [f"[{version}] {p}" for p in found]
        text = "\n\n".join([doc.text, intro, *found])
        acts[at] = (doc.model_copy(update={"text": text}), url, version)


async def _parse(url: str, page: safefetch.Page) -> str:
    """The page's text, parsed once per URL however many claims ask for it at the same time."""
    kept = _parsed.setdefault(asyncio.get_running_loop(), OrderedDict())
    if url not in kept:
        # ponytail: parsed in a thread that a timeout cannot stop; bounded by MAX_PDF_PAGES.
        kept[url] = asyncio.ensure_future(
            asyncio.to_thread(_text, page.body, page.content_type, page.encoding)
        )
        if len(kept) > PARSED_KEPT:
            kept.popitem(last=False)
    task = kept[url]
    try:
        # shield: a claim cut by its deadline does not cancel the parse other claims wait for.
        return await asyncio.shield(task)
    except Exception:
        if kept.get(url) is task and task.done():
            del kept[url]  # a failed parse is tried again by the next claim
        raise


def _text(body: bytes, content_type: str, encoding: str | None) -> str:
    if "pdf" in content_type:
        pages = pypdf.PdfReader(BytesIO(body)).pages[:MAX_PDF_PAGES]
        return "\n".join(p.extract_text() or "" for p in pages)
    parser = lxml.html.HTMLParser(encoding=encoding or "utf-8")
    # Spaces between elements: "<p>Artykuł 2</p><p>Od dnia" must not read "Artykuł 2Od dnia".
    return " ".join(lxml.html.fromstring(body, parser=parser).itertext())


async def _eli(terms: list[str], http: httpx2.AsyncClient) -> list[Act] | None:
    params = {"title": " ".join(terms), "limit": FETCH}
    answer = await _get(str(httpx2.URL(ELI_SEARCH, params=params)), http)
    try:
        items = answer["items"] if answer is not None else None
        return [d for d in map(_eli_doc, items) if d] if items is not None else None
    except (KeyError, TypeError, AttributeError) as exc:
        log.warning("ELI answer not usable: %r", exc)
        return None


async def _eu(terms: list[str], http: httpx2.AsyncClient) -> list[Act] | None:
    query = EU_QUERY.format(terms=" AND ".join(f"'{t}*'" for t in terms), limit=FETCH)
    params = {"query": query, "format": "application/sparql-results+json"}
    answer = await _get(str(httpx2.URL(SPARQL, params=params)), http)
    try:
        rows = answer["results"]["bindings"] if answer is not None else None
        return [d for d in map(_eu_doc, rows) if d] if rows is not None else None
    except (KeyError, TypeError, AttributeError) as exc:
        log.warning("CELLAR answer not usable: %r", exc)
        return None


async def _get(url: str, http: httpx2.AsyncClient) -> dict | None:
    """The JSON answer; None when every attempt failed or the register refused."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            page = await safefetch.get(url, http, allow=_allowed, max_bytes=MAX_BYTES)
        except (safefetch.Blocked, httpx2.InvalidURL) as exc:
            log.info("legal search refused: %s", exc)
            return None
        except httpx2.HTTPError as exc:
            log.warning("legal search attempt %d failed: %r", attempt, exc)
            continue
        if page.status >= 500:
            log.warning("legal search attempt %d: HTTP %d", attempt, page.status)
            continue
        if page.status != 200:  # 403, 429: never worked around
            log.warning("legal search refused: HTTP %d", page.status)
            return None
        try:
            answer = json.loads(page.body)
        except ValueError as exc:
            log.warning("legal search answer not JSON: %r", exc)
            return None
        return answer if isinstance(answer, dict) else None
    return None


def _eli_doc(item: dict) -> Act | None:
    if not isinstance(item, dict):
        return None
    published = _date(item.get("promulgation")) or _date(item.get("announcementDate"))
    title, where = item.get("title"), item.get("displayAddress")
    if not (published and isinstance(title, str) and where and item.get("address")):
        return None
    text = f"{where}: {title}. Status: {item.get('status') or 'nieznany'}."
    text += f" Ogłoszono {published.isoformat()}."
    if force := _date(item.get("entryIntoForce")):
        text += f" Wejście w życie: {force.isoformat()}."
    if repeal := _date(item.get("repealDate")):
        text += f" Uchylono: {repeal.isoformat()}."
    if expired := _date(item.get("expirationDate")):
        text += f" Wygasł: {expired.isoformat()}."
    eli, in_force = item.get("ELI"), item.get("status") == "obowiązujący"
    read = in_force and item.get("textPDF") is True
    read = read and isinstance(eli, str) and re.fullmatch(r"[A-Z]+/\d{4}/\d+", eli)
    doc = Document(
        url=f"https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id={item['address']}",
        title=f"{where}: {title}",
        publisher="Kancelaria Sejmu (ISAP, ELI)",
        published_at=published,
        fetched_at=datetime.now(UTC),
        source_type="official",
        domain="isap.sejm.gov.pl",
        licence="akt normatywny, art. 4 ustawy o prawie autorskim",
        text=text,
    )
    version = f"{where}, tekst ogłoszony {published.isoformat()}"
    return doc, ELI_TEXT.format(eli=eli) if read else None, version


def _eu_doc(row: dict) -> Act | None:
    if not isinstance(row, dict):
        return None
    value = {k: v.get("value") for k, v in row.items() if isinstance(v, dict)}
    celex, title, published = (
        value.get("celex"),
        value.get("title"),
        _date(value.get("date")),
    )
    if not (isinstance(celex, str) and isinstance(title, str) and published):
        return None
    title = " ".join(title.split())  # CELLAR titles use non-breaking spaces
    force = {"1": "obowiązujący", "0": "nieobowiązujący"}.get(value.get("force"))
    text = f"CELEX {celex}: {title}. Data aktu: {published.isoformat()}."
    if force:
        text += f" Status: {force}."
    if eif := _date(value.get("eif")):
        text += f" Wejście w życie: {eif.isoformat()}."
    cons = value.get("cons") if isinstance(value.get("cons"), str) else None
    if cons:
        text += f" Najnowsza wersja skonsolidowana: CELEX {cons}."
    doc = Document(
        url=f"https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:{celex}",
        title=title,
        publisher="EUR-Lex, Urząd Publikacji UE",
        published_at=published,
        fetched_at=datetime.now(UTC),
        source_type="official",
        domain="eur-lex.europa.eu",
        licence="metadane EUR-Lex: CC0; akty: decyzja 2011/833/UE",
        text=text,
    )
    read = force == "obowiązujący" and re.fullmatch(r"[\w()-]+", cons or celex)
    if cons and (stamp := re.search(r"-(\d{4})(\d{2})(\d{2})$", cons)):
        version = f"CELEX {cons}, wersja skonsolidowana z {'-'.join(stamp.groups())}"
    else:
        version = f"CELEX {celex}, tekst opublikowany {published.isoformat()}"
    return doc, EU_TEXT.format(celex=cons or celex) if read else None, version


def _allowed(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in HOSTS


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None
