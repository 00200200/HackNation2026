"""Collectors end to end, offline: the network is a dict of saved pages."""

import asyncio
import json
from urllib.parse import urlencode

import pytest
from fastmcp import FastMCP

from corpus.http import Blocked, FetchError
from corpus.schema import EXCERPT_CHARS, parse_date
from corpus.sources import keyed
from corpus.sources.apis import (
    ELI,
    IMGW,
    ODYSEUSZ,
    act_kind,
    collect_imgw_warnings,
    collect_odyseusz,
    collect_sejm_eli,
    pick_act,
)
from corpus.sources.base import Stopped
from corpus.sources.eurlex import collect_eurlex
from corpus.sources.feeds import collect_feed
from corpus.sources.lists import (
    collect_news_list,
    collect_pages,
    parse_cert,
    parse_policja,
)
from tests.corpus_helpers import fixture, offline_client, source

CERT_LIST = "https://moje.cert.pl/komunikaty/?page={page}"
POLICJA_LIST = "https://policja.pl/pol/aktualnosci?page={page}"
CHALLENGE = '<html><script src="/_Incapsula_Resource?x=1"></script></html>'


def cert_source(**params):
    return source(
        id="cert",
        domain="moje.cert.pl",
        params={"parser": "cert", "list_url": CERT_LIST, **params},
    )


def policja_source(storage="full_text", **params):
    return source(
        id="policja",
        domain="policja.pl",
        storage=storage,
        params={
            "parser": "policja",
            "list_url": POLICJA_LIST,
            "first_page": 0,
            **params,
        },
    )


def cert_urls():
    return [
        i.url
        for i in parse_cert(
            fixture("cert_list.html"), "https://moje.cert.pl/komunikaty/"
        )
    ]


def policja_urls():
    """The saved list has three items; one links to a regional site and is not ours to take."""
    items = parse_policja(fixture("policja_list.html"), "https://policja.pl/pol/")
    assert len(items) == 3
    return [i.url for i in items if i.url.startswith("https://policja.pl/")]


def test_news_list_fetches_articles_and_keeps_dates_and_licence():
    first, second = cert_urls()[:2]
    article = fixture("cert_article.html")
    client = offline_client(
        {
            CERT_LIST.format(page=1): fixture("cert_list.html"),
            first: article,
            second: article,
        }
    )
    docs = collect_news_list(cert_source(max_docs=2), client)
    assert [d.url for d in docs] == [first, second]
    doc = docs[0]
    assert doc.published_at == "2026-11-19"
    assert parse_date(doc.retrieved_at) == doc.retrieved_at
    assert "podszywają się pod Polską Grupę Energetyczną" in doc.text
    assert (doc.licence, doc.storage, doc.truncated) == (
        "CC BY-SA 4.0",
        "full_text",
        False,
    )
    assert (doc.publisher, doc.source_type, doc.language) == (
        "Urząd Testowy",
        "official",
        "pl",
    )
    assert doc.id.startswith("cert-")


def test_excerpt_source_keeps_the_lead_and_never_opens_the_articles():
    calls = []
    client = offline_client(
        {POLICJA_LIST.format(page=0): fixture("policja_list.html")}, calls
    )
    docs = collect_news_list(policja_source(storage="excerpt"), client)
    assert [
        d.url for d in docs
    ] == policja_urls()  # the item on another host is left out
    assert all(d.storage == "excerpt" and d.truncated for d in docs)
    assert all(len(d.text) <= EXCERPT_CHARS + 1 for d in docs)
    assert docs[0].text.startswith("W dniu 17 listopada 2026 r.")
    assert sorted(str(c.url) for c in calls) == sorted(
        ["https://policja.pl/robots.txt", POLICJA_LIST.format(page=0)]
    )


def test_list_without_items_fails_instead_of_returning_nothing():
    client = offline_client(
        {CERT_LIST.format(page=1): "<html><body>przerwa</body></html>"}
    )
    with pytest.raises(FetchError, match="no items"):
        collect_news_list(cert_source(), client)


def test_failing_later_list_page_keeps_the_earlier_ones():
    client = offline_client({POLICJA_LIST.format(page=0): fixture("policja_list.html")})
    docs = collect_news_list(policja_source(storage="excerpt", pages=2), client)
    assert [d.url for d in docs] == policja_urls()


def test_missing_article_is_skipped_and_a_block_stops_the_source():
    first, second = policja_urls()
    article = "<html><body><article><p>Policjanci zatrzymali sprawcę kradzieży.</p></article></body></html>"
    listing = {POLICJA_LIST.format(page=0): fixture("policja_list.html")}
    missing_first = offline_client({**listing, second: article})
    assert [d.url for d in collect_news_list(policja_source(), missing_first)] == [
        second
    ]
    calls = []
    blocked_first = offline_client(
        {**listing, first: CHALLENGE, second: article}, calls
    )
    with pytest.raises(Stopped) as stop:
        collect_news_list(policja_source(), blocked_first)
    assert stop.value.docs == []  # the build keeps the source's older records instead
    assert second not in [
        str(c.url) for c in calls
    ]  # nothing is requested after a block


def test_article_that_redirects_to_another_domain_is_not_taken():
    first, second = policja_urls()
    article = "<html><body><article><p>Komunikat o utrudnieniach w ruchu.</p></article></body></html>"
    client = offline_client(
        {
            POLICJA_LIST.format(page=0): fixture("policja_list.html"),
            first: (301, "https://inny-serwis.pl/komunikat"),
            "https://inny-serwis.pl/komunikat": article,
            second: (302, "https://policja.pl/pol/aktualnosci/nowy-adres.html"),
            "https://policja.pl/pol/aktualnosci/nowy-adres.html": article,
        }
    )
    docs = collect_news_list(policja_source(), client)
    assert [d.url for d in docs] == [
        "https://policja.pl/pol/aktualnosci/nowy-adres.html"
    ]


def test_feed_keeps_only_title_date_and_summary():
    calls = []
    client = offline_client(
        {"https://pravda.org.pl/rss/": fixture("pravda.rss")}, calls
    )
    feed = source(
        id="pravda",
        domain="pravda.org.pl",
        source_type="fact_checker",
        storage="excerpt",
        params={"feeds": ["https://pravda.org.pl/rss/"]},
    )
    docs = collect_feed(feed, client)
    assert len(docs) == 2
    assert docs[0].text.startswith("Bociany odleciały, ale kleszcze zostały.")
    assert docs[0].published_at == "2026-11-13T15:54:07+00:00"
    assert all(
        d.source_type == "fact_checker" and len(d.text) <= EXCERPT_CHARS + 1
        for d in docs
    )
    assert len(calls) == 2  # robots.txt and the feed: no article is opened


FEED = "https://pravda.org.pl/rss/"


def rss(*links: str) -> str:
    items = "".join(
        f"<item><title>Gdzie zgłosić oszustwo?</title><link>{link}</link>"
        "<pubDate>Thu, 19 Nov 2026 15:17:17 +0000</pubDate>"
        "<description>Wyjaśniamy, gdzie zgłosić oszustwo.</description></item>"
        for link in links
    )
    return f'<rss version="2.0"><channel>{items}</channel></rss>'


def feed_source(**params):
    return source(
        id="pravda",
        domain="pravda.org.pl",
        publisher="Stowarzyszenie Pravda",
        source_type="fact_checker",
        storage="excerpt",
        params={"feeds": [FEED], **params},
    )


def test_feed_pages_end_at_the_first_failing_page_and_a_block_stops_the_source():
    first, second = "https://pravda.org.pl/a/", "https://pravda.org.pl/b/"
    feeds = [FEED] + [f"{FEED}?paged={n}" for n in (2, 3, 4)]
    routes = {FEED: rss(first), feeds[1]: rss(second)}
    docs = collect_feed(feed_source(feeds=feeds), offline_client(routes))
    assert [d.url for d in docs] == [first, second]  # page 3 is missing: stop there
    routes[feeds[1]] = (429, "")
    with pytest.raises(Blocked):
        collect_feed(feed_source(feeds=feeds), offline_client(routes))


def eli_query(kind: str, phrase: str) -> str:
    query = {"publisher": "DU", "title": phrase, "type": kind}
    if kind == "Ustawa":
        query["inForce"] = 1  # consolidated texts are searched whatever their status
    return f"{ELI}/acts/search?{urlencode(query)}"


def test_sejm_eli_skips_amendments_and_prefers_the_consolidated_text():
    phrase = "ochronie ludności i obronie cywilnej"
    acts = json.loads(fixture("eli_search.json"))  # two amendments first, then the act
    consolidated = {
        "address": "WDU20260000999",
        "displayAddress": "Dz.U. 2026 poz. 999",
        "publisher": "DU",
        "year": 2026,
        "pos": 999,
        "title": "Obwieszczenie Marszałka Sejmu Rzeczypospolitej Polskiej z dnia 1 października"
        f" 2026 r. w sprawie ogłoszenia jednolitego tekstu ustawy o {phrase}",
        "promulgation": "2026-10-05",
        "textHTML": True,
    }
    routes = {
        eli_query("Ustawa", phrase): json.dumps(acts),
        eli_query("Obwieszczenie", phrase): json.dumps({"items": [consolidated]}),
        f"{ELI}/acts/DU/2026/999/text.html": fixture("eli_text.html"),
        f"{ELI}/acts/DU/2024/1907/text.html": fixture("eli_text.html"),
    }
    eli = source(
        id="sejm",
        domain="api.sejm.gov.pl",
        params={"titles": [phrase], "max_chars": 800},
    )
    (doc,) = collect_sejm_eli(eli, offline_client(routes))
    assert doc.url == f"{ELI}/acts/DU/2026/999/text.html"
    assert doc.published_at == "2026-10-05"
    assert doc.truncated and len(doc.text) <= 801
    assert doc.text.startswith("Ustawa")  # the act itself, not only its footnotes

    routes[eli_query("Obwieszczenie", phrase)] = json.dumps({"items": []})
    (doc,) = collect_sejm_eli(eli, offline_client(routes))
    assert (
        doc.url == f"{ELI}/acts/DU/2024/1907/text.html"
    )  # not the 2026 or 2025 amendment
    assert doc.title.startswith("Ustawa z dnia 5 grudnia 2024 r. o ochronie ludności")
    assert doc.title.endswith("(Dz.U. 2024 poz. 1907)")
    assert doc.published_at == "2024-12-23"


def test_consolidated_text_older_than_the_act_in_force_is_not_taken():
    phrase = "ochronie danych osobowych"
    act = {
        "title": f"Ustawa z dnia 10 maja 2018 r. o {phrase}",
        "promulgation": "2018-05-24",
        "textHTML": True,
    }
    old_text = {
        "title": f"Obwieszczenie Marszałka Sejmu z dnia 1 lutego 2016 r. w sprawie ogłoszenia jednolitego tekstu ustawy o {phrase}",
        "promulgation": "2016-02-10",
        "textHTML": True,
    }
    assert pick_act([old_text, act], phrase) is act
    newer_text = {**old_text, "promulgation": "2019-09-19"}
    assert pick_act([old_text, act, newer_text], phrase) is newer_text


def test_imgw_keeps_the_meteo_warnings_when_hydro_refuses():
    routes = {
        f"{IMGW}/warningsmeteo": fixture("imgw_meteo.json"),
        f"{IMGW}/warningshydro": (429, ""),
    }
    with pytest.raises(Stopped) as stop:
        collect_imgw_warnings(
            source(id="imgw", domain="danepubliczne.imgw.pl"), offline_client(routes)
        )
    assert len(stop.value.docs) == 1


def test_act_kind_reads_the_title():
    phrase = "zarządzaniu kryzysowym"
    assert (
        act_kind("Ustawa z dnia 26 kwietnia 2007 r. o zarządzaniu kryzysowym", phrase)
        == "act"
    )
    assert (
        act_kind("Ustawa z dnia 3 lipca 2002 r. Prawo lotnicze.", "Prawo lotnicze")
        == "act"
    )
    assert (
        act_kind(
            "Ustawa z dnia 1 marca 2020 r. o zmianie ustawy o zarządzaniu kryzysowym",
            phrase,
        )
        is None
    )
    assert (
        act_kind(
            "Ustawa z dnia 5 sierpnia 2015 r. o nadzorze nad systemem finansowym i zarządzaniu"
            " kryzysowym w systemie finansowym",
            phrase,
        )
        is None
    )
    assert (
        act_kind(
            "Rozporządzenie Rady Ministrów w sprawie zarządzaniu kryzysowym", phrase
        )
        is None
    )


def test_imgw_gives_one_record_per_warning_and_survives_no_warnings():
    routes = {
        f"{IMGW}/warningsmeteo": fixture("imgw_meteo.json"),
        f"{IMGW}/warningshydro": fixture("imgw_hydro.json"),
    }
    imgw = source(id="imgw", domain="danepubliczne.imgw.pl")
    docs = collect_imgw_warnings(imgw, offline_client(routes))
    assert len(docs) == 3
    assert len({d.url for d in docs}) == 3
    assert all(d.url.startswith(f"{IMGW}/warnings") and "#" in d.url for d in docs)
    assert (
        docs[0].published_at == "2026-11-21T12:00:00+01:00"
    )  # local time with its offset
    routes[f"{IMGW}/warningsmeteo"] = json.dumps({"status": False, "message": "Brak"})
    assert len(collect_imgw_warnings(imgw, offline_client(routes))) == 2


def test_odyseusz_builds_country_profiles_and_information_pages():
    profile = json.loads(fixture("odyseusz_profile.json"))
    theme = json.loads(fixture("odyseusz_theme.json"))
    code = profile["kodISO"]
    client = offline_client(
        {
            f"{ODYSEUSZ}/profile-panstw/mini": json.dumps(
                [
                    {"kodIso": code, "nazwa": profile["nazwa"]},
                    {"kodIso": "XX", "nazwa": "Brak"},
                ]
            ),
            f"{ODYSEUSZ}/profile-panstw/{code}": json.dumps(profile),
            f"{ODYSEUSZ}/strony-tematyczne/mini": json.dumps(
                [{"kod": theme["kod"], "nazwa": theme["nazwa"], "podstrony": []}]
            ),
            f"{ODYSEUSZ}/strony-tematyczne/{theme['kod']}": json.dumps(theme),
        }
    )
    country, page = collect_odyseusz(
        source(id="odyseusz", domain="odyseusz.gov.pl"), client
    )
    assert country.url == f"{ODYSEUSZ}/profile-panstw/{code}"
    assert country.title == f"{profile['nazwa']} – informacje dla podróżujących"
    assert country.published_at == profile["dataAktualizacji"]
    assert "Ostrzeżenie dla podróżujących: Poziom" in country.text
    assert profile["sekcje"][0]["podsekcje"][0]["tytul"] in country.text
    assert "Miejscowe numery alarmowe: " in country.text
    assert (
        profile["kontaktyPlacowki"][0]["wartosc"] not in country.text
    )  # contacts stay out
    assert "(image removed)" not in country.text
    sub = theme["podstrony"][0]
    assert (
        page.url
        == f"https://odyseusz.gov.pl/strona-tematyczna/{theme['kod']}/{sub['kod']}"
    )
    assert page.title == f"{theme['nazwa']}: {sub['nazwa']}"
    assert page.published_at is None
    assert sub["sekcje"][0]["tytul"] in page.text


def test_eu_acts_come_from_cellar_and_link_to_eurlex():
    calls = []
    cellar = "https://publications.europa.eu/resource/celex/32022R0350"
    client = offline_client({cellar: fixture("eurlex_act.html")}, calls)
    acts = source(
        id="eurlex",
        domain="publications.europa.eu",
        params={"celex": ["32022R0350", "MISSING"]},
    )
    (doc,) = collect_eurlex(acts, client)
    assert (
        doc.url
        == "https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:32022R0350"
    )
    assert doc.title.startswith(
        "ROZPORZĄDZENIE RADY (UE) 2022/350 z dnia 1 marca 2022 r."
    )
    assert doc.published_at == "2022-03-02"
    assert "uwzględniając Traktat o funkcjonowaniu Unii Europejskiej" in doc.text
    request = next(c for c in calls if str(c.url) == cellar)
    assert request.headers["accept-language"] == "pl"
    assert "application/xhtml+xml" in request.headers["accept"]


def test_single_pages_have_no_date_and_foreign_redirects_are_skipped():
    here = "https://www.gov.pl/web/infrastruktura/prawa-pasazerow"
    moved = "https://www.gov.pl/web/dyplomacja/informacje-dla-podrozujacych"
    client = offline_client(
        {
            here: fixture("govpl_page.html"),
            moved: (302, "https://odyseusz.gov.pl"),
            "https://odyseusz.gov.pl": "<html><body><p>Aplikacja Odyseusz</p></body></html>",
        }
    )
    pages = source(id="pages", domain="www.gov.pl", params={"urls": [here, moved]})
    (doc,) = collect_pages(pages, client)
    assert (doc.url, doc.title, doc.published_at) == (here, "Prawa pasażerów", None)


# -- Sources that need a key. The payloads below are made up to match the documented shapes. ----

FACTCHECK_PAGE = {
    "claims": [
        {
            "text": "Przykładowe twierdzenie do testu.",
            "claimant": "Osoba testowa",
            "claimDate": "2026-11-01T00:00:00Z",
            "claimReview": [
                {
                    "publisher": {"name": "Demagog", "site": "demagog.org.pl"},
                    "url": "https://demagog.org.pl/fake_news/przyklad-testowy/",
                    "title": "Przykładowa weryfikacja",
                    "reviewDate": "2026-11-02T00:00:00Z",
                    "textualRating": "Fałsz",
                    "languageCode": "pl",
                }
            ],
        },
        {
            "text": "Twierdzenie ocenione na innej stronie",
            "claimReview": [
                {
                    "publisher": {"name": "Demagog", "site": "demagog.org.pl"},
                    "url": "https://example.com/kopia-weryfikacji/",
                    "textualRating": "Prawda",
                }
            ],
        },
        {
            "text": "Twierdzenie z recenzją bez oceny",
            "claimReview": [
                {
                    "publisher": {"name": "Demagog", "site": "demagog.org.pl"},
                    "url": "https://demagog.org.pl/fake_news/bez-oceny/",
                }
            ],
        },
        {"text": "Twierdzenie bez recenzji"},
    ]
}


def test_google_factcheck_maps_reviews_and_sends_the_key_in_a_header(monkeypatch):
    monkeypatch.setenv("TEST_FACTCHECK_KEY", "klucz-testowy")
    calls = []
    query = urlencode(
        {
            "languageCode": "pl",
            "reviewPublisherSiteFilter": "demagog.org.pl",
            "pageSize": 100,
        }
    )
    client = offline_client(
        {f"{keyed.FACTCHECK_API}?{query}": json.dumps(FACTCHECK_PAGE)}, calls
    )
    google = source(
        id="google",
        domain="factchecktools.googleapis.com",
        source_type="fact_checker",
        storage="excerpt",
        requires_env="TEST_FACTCHECK_KEY",
        params={"publisher_sites": ["demagog.org.pl"]},
    )
    (doc,) = keyed.collect_google_factcheck(google, client)
    assert doc.url == "https://demagog.org.pl/fake_news/przyklad-testowy/"
    assert (doc.title, doc.publisher) == ("Przykładowa weryfikacja", "Demagog")
    assert (
        doc.text
        == "Ocena (Demagog): Fałsz. Sprawdzane twierdzenie: „Przykładowe twierdzenie do testu.”"
    )
    assert doc.published_at == "2026-11-02T00:00:00+00:00"
    assert (doc.claim, doc.rating) == ("Przykładowe twierdzenie do testu.", "Fałsz")
    assert "Osoba testowa" not in doc.model_dump_json()  # the claimant is not collected
    (call,) = calls
    assert call.headers["x-goog-api-key"] == "klucz-testowy"
    assert "klucz-testowy" not in str(call.url)


EUVS_CASES = [
    {
        "id": f"case-{n}",
        "title": f"Test case {n}",
        "claim": f"<p>Made-up claim number {n}.</p>",
        "fact": "Made-up disproof.",
        "date": 1626220800 + n * 86400,
        "countries": [{"_id": "c1", "title": "Poland" if n == 1 else "US"}],
        "linksToDisinformation": [
            {
                "url": f"https://news.example-outlet.ru/a/{n}",
                "archiveUrl": "http://web.archive.org/x",
            },
            {"url": "https://www.youtube.com/watch?v=abc"},
        ],
        "url": f"https://euvsdisinfo.eu/report/test-case-{n}/",
    }
    for n in range(5)
]


def fake_euvsdisinfo() -> FastMCP:
    server = FastMCP("euvsdisinfo-test")

    @server.tool
    def cases(offset: int, limit: int) -> dict:
        batch = EUVS_CASES[offset : offset + limit]
        return {
            "total": 5,
            "cases": batch,
            "hasNextPage": offset + limit < len(EUVS_CASES),
        }

    return server


def test_euvsdisinfo_pages_through_the_cases_tool(monkeypatch):
    monkeypatch.setattr(keyed, "MCP_PAGE", 2)
    fetched = asyncio.run(
        keyed.fetch_cases(fake_euvsdisinfo(), None, limit=10, pause=0)
    )
    assert [c["id"] for c in fetched] == [c["id"] for c in EUVS_CASES]
    capped = asyncio.run(keyed.fetch_cases(fake_euvsdisinfo(), None, limit=3, pause=0))
    assert len(capped) == 3


def test_disinfo_domains_count_cases_per_outlet_and_skip_platforms():
    assert keyed.disinfo_domains(EUVS_CASES) == {"example-outlet.ru": 5}
    assert keyed.disinfo_domains([{"linksToDisinformation": None}, {}]) == {}


def test_euvsdisinfo_writes_records_and_the_domain_list(monkeypatch, tmp_path):
    async def fake_fetch(target, token, limit, pause=1.0):
        assert (target, token) == (keyed.EUVSDISINFO_MCP, "token-testowy")
        return list(EUVS_CASES)

    monkeypatch.setattr(keyed, "fetch_cases", fake_fetch)
    monkeypatch.setenv("TEST_EUVS_TOKEN", "token-testowy")
    out = tmp_path / "domains.json"
    euvs = source(
        id="euvsdisinfo",
        domain="euvsdisinfo.eu",
        source_type="incident_base",
        storage="excerpt",
        language="en",
        requires_env="TEST_EUVS_TOKEN",
        params={"scan_cases": 100, "max_docs": 2, "domains_out": str(out)},
    )
    docs = keyed.collect_euvsdisinfo(euvs, offline_client({}))
    assert [d.url for d in docs] == [
        "https://euvsdisinfo.eu/report/test-case-1/",  # about Poland
        "https://euvsdisinfo.eu/report/test-case-4/",  # then the newest
    ]
    assert (
        docs[0].text
        == "Disproof (EUvsDisinfo): Made-up disproof. Disinformation claim: Made-up claim number 1."
    )
    assert docs[0].claim == "Made-up claim number 1."
    assert (docs[0].published_at, docs[0].language) == ("2021-07-15", "en")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["domains"] == {"example-outlet.ru": 5}
    assert saved["cases_scanned"] == 5
    assert "token-testowy" not in out.read_text(encoding="utf-8")


def test_euvsdisinfo_long_claim_never_pushes_the_disproof_out():
    case = {
        **EUVS_CASES[0],
        "claim": "x " * 400,
        "fact": "The disproof.",
        "date": 1626220800000,
    }
    doc = keyed.case_doc(
        source(
            id="e",
            domain="euvsdisinfo.eu",
            source_type="incident_base",
            storage="excerpt",
        ),
        case,
        "2026-11-21T15:00:00+00:00",
    )
    assert doc.text.startswith("Disproof (EUvsDisinfo): The disproof.")
    assert len(doc.text) <= EXCERPT_CHARS + 1
    assert doc.published_at == "2021-07-14"  # a timestamp in milliseconds is read too


def test_euvsdisinfo_without_cases_keeps_the_old_domain_list(monkeypatch, tmp_path):
    async def no_cases(target, token, limit, pause=1.0):
        return []

    monkeypatch.setattr(keyed, "fetch_cases", no_cases)
    monkeypatch.setenv("TEST_EUVS_TOKEN", "t")
    out = tmp_path / "domains.json"
    out.write_text('{"domains": {"old.example": 1}}')
    euvs = source(
        id="euvsdisinfo",
        domain="euvsdisinfo.eu",
        source_type="incident_base",
        storage="excerpt",
        requires_env="TEST_EUVS_TOKEN",
        params={"scan_cases": 10, "max_docs": 2, "domains_out": str(out)},
    )
    with pytest.raises(FetchError, match="no cases"):
        keyed.collect_euvsdisinfo(euvs, offline_client({}))
    assert "old.example" in out.read_text()


def test_odyseusz_stops_at_a_refusal_and_keeps_what_it_has():
    profile = json.loads(fixture("odyseusz_profile.json"))
    calls = []
    routes = {
        f"{ODYSEUSZ}/profile-panstw/mini": json.dumps(
            [{"kodIso": c, "nazwa": c} for c in ("IT", "AA", "BB")]
        ),
        f"{ODYSEUSZ}/profile-panstw/IT": json.dumps(profile),
        f"{ODYSEUSZ}/profile-panstw/AA": (429, ""),
        f"{ODYSEUSZ}/strony-tematyczne/mini": "[]",
    }
    with pytest.raises(Stopped) as stop:
        collect_odyseusz(
            source(id="o", domain="odyseusz.gov.pl"), offline_client(routes, calls)
        )
    assert [d.url for d in stop.value.docs] == [f"{ODYSEUSZ}/profile-panstw/IT"]
    requested = [str(c.url) for c in calls]
    assert f"{ODYSEUSZ}/profile-panstw/BB" not in requested
    assert f"{ODYSEUSZ}/strony-tematyczne/mini" not in requested


def test_pages_and_eu_acts_stop_at_a_refusal():
    pages = source(
        id="pages",
        domain="www.gov.pl",
        params={"urls": ["https://www.gov.pl/a", "https://www.gov.pl/b"]},
    )
    calls = []
    with pytest.raises(Stopped):
        collect_pages(pages, offline_client({"https://www.gov.pl/a": (403, "")}, calls))
    assert "https://www.gov.pl/b" not in [str(c.url) for c in calls]

    cellar = "https://publications.europa.eu/resource/celex/{}"
    acts = source(
        id="eu", domain="publications.europa.eu", params={"celex": ["A", "B", "C"]}
    )
    calls = []
    client = offline_client(
        {cellar.format("A"): fixture("eurlex_act.html"), cellar.format("B"): (202, "")},
        calls,
    )
    with pytest.raises(Stopped) as stop:
        collect_eurlex(acts, client)
    assert len(stop.value.docs) == 1
    assert cellar.format("C") not in [str(c.url) for c in calls]


def test_odyseusz_keeps_country_profiles_when_the_page_index_fails():
    profile = json.loads(fixture("odyseusz_profile.json"))
    routes = {
        f"{ODYSEUSZ}/profile-panstw/mini": json.dumps(
            [{"kodIso": "IT", "nazwa": "Włochy"}]
        ),
        f"{ODYSEUSZ}/profile-panstw/IT": json.dumps(profile),
        f"{ODYSEUSZ}/strony-tematyczne/mini": (500, ""),
    }
    with pytest.raises(Stopped, match="information pages unavailable") as stop:
        collect_odyseusz(
            source(id="o", domain="odyseusz.gov.pl"), offline_client(routes, retries=0)
        )
    assert [d.url for d in stop.value.docs] == [f"{ODYSEUSZ}/profile-panstw/IT"]
