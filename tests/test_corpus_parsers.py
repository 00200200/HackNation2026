"""Parsers run on pages saved from the live sites on 2026-11-21 (tests/fixtures/corpus)."""

import json

import pytest

from corpus.extract import main_text, plain_text
from corpus.schema import (
    Doc,
    clip,
    mask_emails,
    parse_date,
    read_jsonl,
    registered_domain,
    strict_domain,
    write_jsonl,
)
from corpus.sources.apis import hydro_warning, meteo_warning
from corpus.sources.eurlex import act_header
from corpus.sources.feeds import parse_feed, parse_review, review_text, without_tracking
from corpus.sources.lists import (
    page_title,
    parse_cert,
    parse_govpl,
    parse_gus,
    parse_policja,
)
from tests.corpus_helpers import fixture


def test_govpl_list_gives_dated_items_with_absolute_links():
    items = parse_govpl(
        fixture("govpl_list.html"), "https://www.gov.pl/web/rcb/komunikaty"
    )
    assert len(items) == 3
    first = items[0]
    assert (
        first.url
        == "https://www.gov.pl/web/rcb/alert-rcb---trening-systemow-alarmowania-2111"
    )
    assert first.title == "Alert RCB - trening systemów alarmowania (21.11)"
    assert first.published_at == "2026-11-21"
    assert "trening systemu alarmowania" in first.lead


def test_govpl_list_ignores_blocks_without_a_date():
    html = '<div class="art-prev"><ul><li><div class="title"><a href="/web/x/y">Poradniki</a></div></li></ul></div>'
    assert parse_govpl(html, "https://www.gov.pl/web/x") == []


def test_cert_list_gives_every_advisory_with_its_date():
    items = parse_cert(fixture("cert_list.html"), "https://moje.cert.pl/komunikaty/")
    assert len(items) == 10
    first = items[0]
    assert first.url.startswith("https://moje.cert.pl/komunikaty/2026/218/")
    assert "Fałszywe informacje o zwrocie za energię elektryczną" in first.title
    assert first.published_at == "2026-11-19"
    assert "kampanię phishingową" in first.lead
    assert all(
        i.published_at and i.url.startswith("https://moje.cert.pl/") for i in items
    )


def test_policja_list_reads_title_lead_and_machine_date():
    items = parse_policja(
        fixture("policja_list.html"), "https://policja.pl/pol/aktualnosci?page=2"
    )
    assert len(items) == 3
    assert items[0].url.startswith("https://policja.pl/pol/aktualnosci/284017,")
    assert items[0].title.startswith("Gala finałowa ogólnopolskiego konkursu")
    assert items[0].published_at == "2026-11-17"
    assert items[0].lead.startswith("W dniu 17 listopada 2026 r.")


def test_gus_list_reads_title_and_machine_date():
    items = parse_gus(fixture("gus_list.html"), "https://new.stat.gov.pl/aktualnosci")
    assert len(items) == 3
    assert (
        items[1].url
        == "https://new.stat.gov.pl/aktualnosci/biezace-informacje-o-inflacji"
    )
    assert items[1].title == "Bieżące informacje o inflacji"
    assert items[1].published_at == "2026-11-13T09:33:00+01:00"


def test_page_title_and_main_text_leave_out_menu_and_footer():
    html = fixture("govpl_page.html")
    assert page_title(html) == "Prawa pasażerów"
    text = main_text(html, "https://www.gov.pl/web/infrastruktura/prawa-pasazerow")
    assert "rozporządzenia Parlamentu Europejskiego i Rady (UE) nr 181/2011" in text
    assert "Creative Commons" not in text  # footer
    assert "Co robimy" not in text  # menu


def test_main_text_of_an_advisory_keeps_the_warning():
    text = main_text(
        fixture("cert_article.html"), "https://moje.cert.pl/komunikaty/2026/218/x/"
    )
    assert "podszywają się pod Polską Grupę Energetyczną" in text
    assert main_text("<html><body></body></html>", "https://a.pl/") is None


def test_claim_review_without_a_marked_summary_falls_back_to_the_description():
    page = fixture("demagog_claimreview.html")
    review = parse_review(page, "https://demagog.org.pl/wypowiedzi/x/")
    assert review.rating == "Fałsz"
    assert review.links == []  # links are read only from the marked summary
    text = review_text(review, "Stowarzyszenie Demagog")
    assert text.startswith(
        "Ocena (Stowarzyszenie Demagog): Fałsz. Sprawdzane twierdzenie: „Potępiam"
    )
    assert text.endswith("Wyjaśniamy, gdzie można zgłosić oszustwo.")
    empty = parse_review("<html><head></head><body>x</body></html>", "https://a.pl/")
    assert (empty.claim, empty.rating, review_text(empty, "X")) == (None, None, "")


def test_eurlex_header_gives_the_act_title_and_journal_date():
    title, published = act_header(fixture("eurlex_act.html"))
    assert title.startswith(
        "ROZPORZĄDZENIE RADY (UE) 2022/350 z dnia 1 marca 2022 r. w sprawie zmiany"
    )
    assert published == "2022-03-02"
    assert act_header("<html><body><p>nic</p></body></html>") == (None, None)


def test_eurlex_header_of_an_act_in_the_older_layout():
    title, published = act_header(fixture("eurlex_act_old.html"))
    assert title.startswith(
        "Rozporządzenie (WE) nr 261/2004 Parlamentu Europejskiego i Rady z dnia 11 lutego 2004 r. ustanawiające"
    )
    assert title.endswith("uchylające rozporządzenie (EWG) nr 295/91")
    assert published == "2004-02-17"


def test_feed_entries_have_utc_dates_and_plain_summaries():
    items = parse_feed(fixture("pravda.rss"))
    assert len(items) == 2
    assert (
        items[0].title == "5 rzeczy, które pseudomedycyna chce Ci wmówić o boreliozie"
    )
    assert items[0].url.startswith("https://pravda.org.pl/")
    assert items[0].published_at == "2026-11-13T15:54:07+00:00"
    assert items[0].lead.startswith("Bociany odleciały, ale kleszcze zostały.")
    assert "<" not in items[0].lead


def test_feed_boilerplate_is_dropped_and_a_page_that_is_not_a_feed_has_no_entries():
    xml = (
        '<rss version="2.0"><channel><item><title>T</title><link>https://a.pl/t</link>'
        "<description>&lt;p&gt;Artykuł &lt;a href='x'&gt;T&lt;/a&gt; pochodzi z serwisu Demagog.&lt;/p&gt;"
        "</description></item></channel></rss>"
    )
    assert (
        parse_feed(xml, drop=r"Artykuł .{0,300}? pochodzi z serwisu Demagog\s*\.")[
            0
        ].lead
        == ""
    )
    assert parse_feed("<html><body>Just a moment...</body></html>") == []


def test_imgw_records_keep_the_published_wording():
    meteo = json.loads(fixture("imgw_meteo.json"))[0]
    fragment, title, text = meteo_warning(meteo)
    assert fragment == meteo["id"]
    assert title == "Ostrzeżenie meteorologiczne: Oblodzenie, stopień 1"
    assert meteo["tresc"] in text
    assert "Obowiązuje od 2026-11-22 01:00:00 do 2026-11-22 08:00:00." in text
    assert "Komentarz" not in text  # the API sends "Brak." when there is none

    hydro = json.loads(fixture("imgw_hydro.json"))[0]
    fragment, title, text = hydro_warning(hydro)
    assert fragment == "21-20260417084556"
    assert title == "Ostrzeżenie hydrologiczne nr 21: Susza hydrologiczna, stopień -1"
    assert hydro["przebieg"] in text
    assert "do odwołania." in text
    assert "łódzkie, Warta górna z Liswartą, susza hydrologiczna" in text


def test_domains_are_counted_by_registered_domain():
    assert registered_domain("https://www.gov.pl/web/rcb/komunikaty") == "www.gov.pl"
    assert registered_domain("https://www.gov.pl/web/mswia") == "www.gov.pl"
    assert registered_domain("https://api.sejm.gov.pl/eli/acts") == "sejm.gov.pl"
    assert registered_domain("https://moje.cert.pl/komunikaty/") == "cert.pl"
    assert strict_domain("https://api.sejm.gov.pl/eli/acts") == "gov.pl"
    assert strict_domain("https://www.gov.pl/web/rcb") == "gov.pl"
    assert strict_domain("https://policja.pl/pol/") == "policja.pl"


def test_dates_are_normalised_or_rejected():
    assert parse_date("21.11.2026") == "2026-11-21"
    assert parse_date("19-11-2026") == "2026-11-19"
    assert parse_date("2.3.2022") == "2022-03-02"
    assert parse_date("2026-11-21 12:00:00") == "2026-11-21T12:00:00"
    assert parse_date("2026-11-17") == "2026-11-17"
    assert parse_date("31.02.2026") is None
    assert parse_date("[218/2026]") is None
    assert parse_date(None) is None


def test_text_helpers():
    assert clip("krótki tekst", 50) == ("krótki tekst", False)
    assert clip("jeden dwa trzy cztery", 12) == ("jeden dwa…", True)
    assert (
        mask_emails("pisz na jan.kowalski@urzad.gov.pl dziś")
        == "pisz na [adres e-mail usunięty] dziś"
    )
    assert plain_text("<p>Ala&nbsp;ma <b>kota</b></p>") == "Ala ma kota"
    assert plain_text(None) == ""


def test_record_validation_and_jsonl_round_trip(tmp_path):
    fields = {
        "id": "s-1",
        "url": "https://a.gov.pl/1",
        "title": "Tytuł",
        "publisher": "Urząd",
        "published_at": None,
        "retrieved_at": "2026-11-21T15:00:00+00:00",
        "source_type": "official",
        "licence": "CC BY-SA 4.0",
        "language": "pl",
        "text": "Treść",
        "source_id": "s",
        "storage": "full_text",
    }
    doc = Doc(**fields)
    write_jsonl([doc], tmp_path / "docs.jsonl")
    assert read_jsonl(tmp_path / "docs.jsonl") == [doc]
    row = json.loads((tmp_path / "docs.jsonl").read_text(encoding="utf-8"))
    assert {"id", "url", "title", "publisher", "published_at", "retrieved_at"} <= set(
        row
    )
    assert {"source_type", "licence", "language", "text"} <= set(row)
    with pytest.raises(ValueError):
        Doc(**{**fields, "text": "  "})
    with pytest.raises(ValueError):
        Doc(**{**fields, "published_at": "21.11.2026"})
    with pytest.raises(ValueError):
        Doc(**{**fields, "source_type": "blog"})


def test_cited_links_lose_tracking_and_skip_posts_archives_and_banned_domains():
    assert (
        without_tracking("https://kross.pl/r?srsltid=Afm1&x=1#top")
        == "https://kross.pl/r?x=1"
    )
    assert (
        without_tracking("https://a.pl/x?utm_source=fb&id=5") == "https://a.pl/x?id=5"
    )
    assert (
        without_tracking("https://sip.lex.pl/art-239?utm_=")
        == "https://sip.lex.pl/art-239"
    )
    summary = (
        '<div class="summary-text"><a href="https://www.threads.com/@a/post/1">1</a>'
        '<a href="https://archive.is/abc">2</a><a href="https://fb.watch/x">3</a>'
        '<a href="https://news.example-outlet.ru/a">4</a><a href="/inny-tekst/">5</a>'
        '<a href="http://m.in">m.in</a>'
        '<a href="https://www.gov.pl/web/x?fbclid=1">komunikat</a></div>'
    )
    review = parse_review(
        f"<html><body>{summary}</body></html>",
        "https://demagog.org.pl/fake_news/x/",
        '//div[@class="summary-text"]',
        frozenset({"example-outlet.ru"}),
    )
    assert [(link.url, link.text) for link in review.links] == [
        ("https://www.gov.pl/web/x", "komunikat")
    ]


def test_odd_claim_review_shapes_do_not_break_the_parser():
    page = (
        '<html><head><script type="application/ld+json">{"@type": "ClaimReview",'
        ' "claimReviewed": ["lista"], "itemReviewed": "tekst", "author": [],'
        ' "reviewRating": {"alternateName": ["Fałsz", "False"]}}</script></head><body></body></html>'
    )
    review = parse_review(page, "https://demagog.org.pl/x/")
    assert (review.rating, review.author, review.first_appearance) == (
        "Fałsz",
        None,
        None,
    )
    assert review.claim == "lista"


def test_query_keeps_everything_but_tracking_as_written():
    assert (
        without_tracking("https://titania.saeima.lv/x?OpenDocument")
        == "https://titania.saeima.lv/x?OpenDocument"
    )
    assert (
        without_tracking("https://eur-lex.europa.eu/x?uri=CELEX%3A32022R0350&utm=a")
        == "https://eur-lex.europa.eu/x?uri=CELEX%3A32022R0350"
    )
