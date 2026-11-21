"""Official JSON endpoints without keys: Sejm ELI (legal acts), IMGW-PIB (weather warnings)
and Odyseusz (travel information of the Ministry of Foreign Affairs)."""

import json
import logging
import re
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from corpus.catalog import Source
from corpus.extract import all_text
from corpus.http import Blocked, FetchError, PoliteClient
from corpus.schema import Doc, parse_date
from corpus.sources.base import Stopped, make_doc

log = logging.getLogger("corpus")

ELI = "https://api.sejm.gov.pl/eli"
IMGW = "https://danepubliczne.imgw.pl/api/data"
NO_END_DATE = "9999-12-31"  # IMGW marks a warning that is valid until it is cancelled
ODYSEUSZ = "https://odyseusz.gov.pl/api/v1/informacje"
ODYSEUSZ_PAGE = "https://odyseusz.gov.pl/strona-tematyczna"
WARSAW = ZoneInfo("Europe/Warsaw")


# A title naming an amendment, a ratification or an implementing act is not the act itself.
AMENDING = re.compile(r"(?i)o zmianie|zmieniając|ratyfikac|wprowadzając|uchyleni")


def act_kind(title: str, phrase: str) -> str | None:
    """ "consolidated" for the announcement of a consolidated text of the act named by `phrase`,
    "act" for the act itself, None for anything else (amendments, regulations, other acts)."""
    text = " ".join(title.lower().rstrip(" .").split())
    if AMENDING.search(text) or not text.endswith(phrase.lower()):
        return None
    if "jednolitego tekstu ustawy" in text:
        return "consolidated"
    return "act" if text.startswith("ustawa z dnia") else None


def pick_act(found: list[dict], phrase: str) -> dict | None:
    """The newest consolidated text with an HTML version, otherwise the act itself. A
    consolidated text older than the act in force belongs to an earlier act of the same name."""
    acts = [a for a in found if act_kind(a["title"], phrase) == "act"]
    since = max((a.get("promulgation") or "" for a in acts), default="")
    candidates = [
        a
        for a in found
        if a.get("textHTML")
        and act_kind(a["title"], phrase)
        and (a.get("promulgation") or "") >= since
    ]
    candidates.sort(
        key=lambda a: (
            act_kind(a["title"], phrase) == "consolidated",
            a.get("promulgation") or "",
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def collect_sejm_eli(source: Source, client: PoliteClient) -> list[Doc]:
    """For every phrase in params.titles, the act in force whose title ends with it ("... o
    ochronie ludności i obronie cywilnej"): its newest consolidated text that has an HTML version,
    otherwise the original text of the act.

    Only versions with an HTML text are taken (acts from 2025 on are PDF only).
    params: titles, max_chars.
    """
    docs: dict[str, Doc] = {}
    for phrase in source.params["titles"]:
        found = []
        # A consolidated text is marked "not in force" once a newer one exists, and the newest
        # ones are PDF only; so consolidated texts are searched regardless of that status.
        # The API's default page (500) holds every match; `pick_act` does the ordering.
        for search in ({"type": "Obwieszczenie"}, {"type": "Ustawa", "inForce": 1}):
            query = urlencode({"publisher": "DU", "title": phrase, **search})
            try:
                found += client.get_json(
                    f"{ELI}/acts/search?{query}", max_age=source.max_age
                ).get("items", [])
            except Blocked as exc:
                raise Stopped(str(exc), list(docs.values())) from exc
            except (FetchError, json.JSONDecodeError) as exc:
                log.warning("%s: search for %r failed (%s)", source.id, phrase, exc)
        act = pick_act(found, phrase)
        if act is None:
            log.warning(
                "%s: no act or consolidated text with HTML for %r", source.id, phrase
            )
            continue
        url = f"{ELI}/acts/{act['publisher']}/{act['year']}/{act['pos']}/text.html"
        if url in docs:
            continue
        try:
            page = client.get(url, max_age=source.max_age)
        except Blocked as exc:
            raise Stopped(str(exc), list(docs.values())) from exc
        except FetchError as exc:
            log.warning("%s: skipped %s (%s)", source.id, url, exc)
            continue
        doc = make_doc(
            source,
            url=url,
            title=f"{act['title']} ({act['displayAddress']})",
            text=all_text(page.text) or "",
            published_at=parse_date(act.get("promulgation")),
            retrieved_at=page.fetched_at,
        )
        if doc is None:
            log.warning("%s: no text in %s", source.id, url)
        else:
            docs[url] = doc
    return list(docs.values())


def _lines(*parts: str | None) -> str:
    return "\n".join(
        p.strip() for p in parts if p and p.strip() and p.strip() != "Brak."
    )


def meteo_warning(w: dict) -> tuple[str, str, str]:
    """(fragment id, title, text) of one record of `warningsmeteo`. Values are verbatim."""
    head = f"{w['nazwa_zdarzenia']}, stopień {w['stopien']}"
    text = _lines(
        f"Ostrzeżenie meteorologiczne IMGW-PIB: {head}.",
        f"Obowiązuje od {w['obowiazuje_od']} do {w['obowiazuje_do']}.",
        f"Prawdopodobieństwo: {w['prawdopodobienstwo']}%.",
        w.get("tresc"),
        f"Komentarz: {w['komentarz']}"
        if w.get("komentarz") not in (None, "", "Brak.")
        else None,
        f"Wydało: {w['biuro']}." if w.get("biuro") else None,
        f"Powiaty (kody TERYT): {', '.join(w['teryt'])}." if w.get("teryt") else None,
    )
    return str(w["id"]), f"Ostrzeżenie meteorologiczne: {head}", text


def hydro_warning(w: dict) -> tuple[str, str, str]:
    """(fragment id, title, text) of one record of `warningshydro`. Values are verbatim."""
    head = f"{w['zdarzenie']}, stopień {w['stopień']}"
    until = "odwołania" if w["data_do"].startswith(NO_END_DATE) else w["data_do"]
    areas = "; ".join(a["opis"] for a in w.get("obszary", []) if a.get("opis"))
    text = _lines(
        f"Ostrzeżenie hydrologiczne IMGW-PIB nr {w['numer']}: {head}.",
        f"Obowiązuje od {w['data_od']} do {until}.",
        f"Prawdopodobieństwo: {w['prawdopodobienstwo']}%.",
        w.get("przebieg"),
        f"Komentarz: {w['komentarz']}"
        if w.get("komentarz") not in (None, "", "Brak.")
        else None,
        f"Obszary: {areas}." if areas else None,
        f"Wydało: {w['biuro']}." if w.get("biuro") else None,
    )
    fragment = f"{w['numer']}-{re.sub(r'[^0-9]', '', w['opublikowano'])}"
    return fragment, f"Ostrzeżenie hydrologiczne nr {w['numer']}: {head}", text


def warsaw_time(value: str | None) -> str | None:
    """IMGW gives local time without a zone ("2026-11-21 12:00:00"); return it with the offset."""
    try:
        return (
            datetime.strptime(value or "", "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=WARSAW)
            .isoformat()
        )
    except ValueError:
        return None


def collect_imgw_warnings(source: Source, client: PoliteClient) -> list[Doc]:
    """A snapshot of the warnings valid at build time, one record per warning.

    The API has no address per warning, so the record URL is the endpoint plus a fragment.
    """
    docs = []
    for endpoint, build in (
        ("warningsmeteo", meteo_warning),
        ("warningshydro", hydro_warning),
    ):
        try:
            page = client.get(f"{IMGW}/{endpoint}", max_age=source.max_age)
            warnings = json.loads(page.text)
        except Blocked as exc:
            raise Stopped(str(exc), docs) from exc
        except (FetchError, json.JSONDecodeError) as exc:
            log.warning("%s: %s failed (%s)", source.id, endpoint, exc)
            continue
        if not isinstance(
            warnings, list
        ):  # an object instead of a list when there are none
            log.info("%s: %s has no warnings now", source.id, endpoint)
            continue
        for warning in warnings:
            try:
                fragment, title, text = build(warning)
            except (KeyError, TypeError, AttributeError) as exc:
                log.warning("%s: unexpected %s record (%r)", source.id, endpoint, exc)
                continue
            doc = make_doc(
                source,
                url=f"{IMGW}/{endpoint}#{fragment}",
                title=title,
                text=text,
                published_at=warsaw_time(warning.get("opublikowano")),
                retrieved_at=page.fetched_at,
            )
            if doc is not None:
                docs.append(doc)
    return docs


def _sections(sections: list[dict], heading: str) -> list[str | None]:
    """Titles and texts of `sekcje` and their `podsekcje`, in the order the portal shows them."""
    parts: list[str | None] = []
    for section in sections or []:
        parts += [
            section.get(heading),
            section.get("podsumowanie"),
            section.get("tresc"),
        ]
        for sub in section.get("podsekcje") or []:
            parts += [sub.get("tytul"), sub.get("tresc")]
    return parts


def country_text(profile: dict) -> str:
    """Text of one Odyseusz country profile: the current notice and the warnings first, then
    the sections. Consular contact details and the flag image are left out."""
    parts: list[str | None] = []
    if notice := profile.get("trescPowiadomieniaDluga"):
        parts.append(f"Komunikat MSZ: {notice}")
    for warning in profile.get("ostrzezenia") or []:
        level = (warning.get("poziomZagrozenia") or {}).get("opis")
        scope = (warning.get("zakresTerytorialnyOstrzezenia") or {}).get("opis")
        since = warning.get("dataObowiazywaniaOd")
        parts.append(
            f"Ostrzeżenie dla podróżujących: {level} ({scope}), obowiązuje od {since}."
        )
        parts.append(warning.get("tresc"))
    for section in profile.get("sekcje") or []:
        section = {
            **section,
            "nazwa": (section.get("zakresInformacyjny") or {}).get("opis"),
        }
        parts += _sections([section], "nazwa")
    numbers = "; ".join(
        f"{n['nazwa']}: {n['wartosc']}"
        for n in profile.get("miejscoweNumeryAlarmowe") or []
        if n.get("nazwa") and n.get("wartosc")
    )
    if numbers:
        parts.append(f"Miejscowe numery alarmowe: {numbers}")
    return _lines(*parts)


def collect_odyseusz(source: Source, client: PoliteClient) -> list[Doc]:
    """Country profiles and information pages of odyseusz.gov.pl.

    The portal is a single-page app, so the text comes from the public JSON endpoints its own
    pages call. A country record links to that endpoint; an information page has a public
    address. When the site starts refusing us, the collector stops and keeps what it has.
    params: max_chars.
    """
    docs: list[Doc] = []
    try:
        for country in client.get_json(
            f"{ODYSEUSZ}/profile-panstw/mini", max_age=source.max_age
        ):
            url = f"{ODYSEUSZ}/profile-panstw/{country['kodIso']}"
            try:
                page = client.get(url, max_age=source.max_age)
                profile = json.loads(page.text)
            except Blocked:
                raise
            except (FetchError, json.JSONDecodeError) as exc:
                log.warning("%s: skipped %s (%s)", source.id, url, exc)
                continue
            doc = make_doc(
                source,
                url=url,
                title=f"{profile.get('nazwa') or country['nazwa']} – informacje dla podróżujących",
                text=country_text(profile),
                published_at=parse_date(profile.get("dataAktualizacji")),
                retrieved_at=page.fetched_at,
            )
            if doc is not None:
                docs.append(doc)
        try:
            themes = client.get_json(
                f"{ODYSEUSZ}/strony-tematyczne/mini", max_age=source.max_age
            )
        except Blocked:
            raise
        except (FetchError, json.JSONDecodeError) as exc:
            # Country profiles are in; the build keeps the older information pages.
            raise Stopped(f"information pages unavailable ({exc})", docs) from exc
        for theme in themes:
            try:
                page = client.get(
                    f"{ODYSEUSZ}/strony-tematyczne/{theme['kod']}",
                    max_age=source.max_age,
                )
                subpages = json.loads(page.text).get("podstrony") or []
            except Blocked:
                raise
            except (FetchError, json.JSONDecodeError) as exc:
                log.warning(
                    "%s: skipped theme %s (%s)", source.id, theme.get("kod"), exc
                )
                continue
            for sub in subpages:
                doc = make_doc(
                    source,
                    url=f"{ODYSEUSZ_PAGE}/{theme['kod']}/{sub['kod']}",
                    title=f"{theme['nazwa']}: {sub['nazwa']}",
                    text=_lines(*_sections(sub.get("sekcje"), "tytul")),
                    published_at=None,
                    retrieved_at=page.fetched_at,
                )
                if doc is not None:
                    docs.append(doc)
    except Blocked as exc:
        raise Stopped(str(exc), docs) from exc
    return docs
