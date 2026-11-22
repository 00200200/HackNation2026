"""G01 (quick eval on ca48b84): every judge quote was dropped, the Demagog "Fałsz" record included.
Forms a judge returns for a ClaimReview record or a page, and what the check keeps."""

from datetime import UTC, date, datetime

import pytest

from prawdowid import factcheck
from prawdowid.contract import Source, Verdict
from prawdowid.judge import Label, decide, find_quote, verify_quotes
from prawdowid.rerank import Fragment, canonical_url

URL = "https://demagog.org.pl/fake_news/kibice-ida-bronic-trybunalu-przed-tuskiem-nie-przyjechali-na-mecz-legia-wisla/"
CLAIM = "Kibice Legii Warszawa poszli protestować pod Trybunał Konstytucyjny."
TITLE = (
    "Kibice idą bronić Trybunału przed Tuskiem? Nie, przyjechali na mecz Legia–Wisła"
)
TODAY = date(2026, 11, 22)


def record(rating="Fałsz", claim=CLAIM):
    source = Source(
        title=TITLE,
        publisher="Demagog",
        published_at=date(2026, 11, 3),
        fetched_at=datetime(2026, 11, 22, tzinfo=UTC),
        url=URL,
        source_type="fact_check",
        fragment=factcheck.review_fragment(rating, claim),
    )
    return Fragment(doc_id=canonical_url(URL), source=source)


def page(text, url="https://wideo.pap.pl/pap-media,101/manifestacja,99518"):
    source = Source(
        title="Manifestacja przed Trybunałem Konstytucyjnym",
        publisher="Polska Agencja Prasowa",
        published_at=date(2026, 10, 30),
        fetched_at=datetime(2026, 11, 22, tzinfo=UTC),
        url=url,
        source_type="news",
        fragment=text,
    )
    return Fragment(doc_id=canonical_url(url), source=source)


def rated(quote, doc_id=None, fragment=None):
    f = fragment or record()
    label = Label(
        doc_id=doc_id or f.doc_id,
        stance="refutes",
        quote=quote,
        own_conclusion=True,
        same_claim=True,
    )
    return decide(verify_quotes([label], [f]), [], TODAY)


@pytest.mark.parametrize(
    "quote",
    [
        "Ocena fact-checkera: Fałsz.",
        "Fałsz",
        "Fałsz.",
        "fałsz",
        f"Ocena fact-checkera: Fałsz. Sprawdzane twierdzenie: {CLAIM}",
        f"Ocena fact-checkera: Fałsz.\n\nSprawdzane twierdzenie: {CLAIM}",
        "Ocena fact-checkera: Fałsz. Sprawdzane twierdzenie: Kibice Legii Warszawa",
    ],
)
def test_every_form_of_the_rating_line_reads_the_rating(quote):
    j = rated(quote)
    assert j.verdict is Verdict.FALSE
    assert j.sources[0].rating == "Fałsz" and j.sources[0].fragment == "Fałsz"


@pytest.mark.parametrize(
    "quote",
    [
        CLAIM,  # the disputed statement is not the fact-checker's finding
        f"Sprawdzane twierdzenie: {CLAIM}",
        "Ocena fact-checkera: Fałsz. Kibice przyjechali na mecz.",  # words not in the record
        "Ocena fact-checkera: Prawda.",  # another rating
    ],
)
def test_the_record_gives_nothing_for_any_other_quote(quote):
    j = rated(quote)
    assert j.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert j.sources == [] or all(s.rating is None for s in j.sources)


@pytest.mark.parametrize(
    "doc_id",
    [URL, URL.replace("https://", "https://www."), URL.replace("https://", "http://")],
)
def test_a_doc_id_written_another_way_names_the_same_document(doc_id):
    assert rated("Ocena fact-checkera: Fałsz.", doc_id=doc_id).verdict is Verdict.FALSE


def test_a_doc_id_of_another_document_names_none():
    assert (
        rated("Ocena fact-checkera: Fałsz.", doc_id="https://demagog.org.pl/x").verdict
        is Verdict.INSUFFICIENT_EVIDENCE
    )


def test_a_decoded_comma_in_the_doc_id_still_names_the_page():
    f = page(
        "W piątek wieczorem trwa manifestacja przed siedzibą Trybunału Konstytucyjnego."
    )
    label = Label(
        doc_id="https://wideo.pap.pl/pap-media,101/manifestacja,99518",
        stance="context",
        quote="W piątek wieczorem trwa manifestacja przed siedzibą Trybunału Konstytucyjnego.",
    )
    assert f.doc_id.count("%2C") == 2
    assert verify_quotes([label], [f])


@pytest.mark.parametrize(
    "quote, text",
    [
        # A full stop or quote marks the model adds at the ends of a copy.
        ("Nie, przyjechali na mecz Legia–Wisła.", TITLE),
        ("„Nie, przyjechali na mecz Legia–Wisła”", TITLE),
        (
            "...trwa manifestacja przed siedzibą Trybunału…",
            "Dziś trwa manifestacja przed siedzibą Trybunału.",
        ),
        # A soft hyphen or zero-width space no model copies.
        (
            "manifestacja przed siedzibą Trybunału",
            "Trwa manifes­tacja przed sie\u200bdzibą Trybunału.",
        ),
    ],
)
def test_edge_punctuation_and_invisible_characters_do_not_drop_a_copy(quote, text):
    assert find_quote(quote, text)


@pytest.mark.parametrize(
    "quote, text",
    [
        # Still strict on the words, numbers and signs of real page text.
        (
            "przyjechało 1,5 tys. kibiców z Krakowa",
            "przyjechało 1,6 tys. kibiców z Krakowa",
        ),
        ("wzrost o 10 procent rocznie", "wzrost o -10 procent rocznie"),
        (
            "Kibice przyjechali na mecz Legii",
            "Kibice przyjechali na mecz, nie na protest.",
        ),
        (
            "kończy się tutaj. Drugi fragment zaczyna",
            "Pierwszy fragment kończy się tutaj.\n\nDrugi fragment zaczyna się.",
        ),
        # Words cut from a question are no statement, with or without a full stop.
        ("Kibice idą bronić Trybunału przed Tuskiem", TITLE),
        ("Kibice idą bronić Trybunału przed Tuskiem.", TITLE),
        ("Fałsz", "Ocena: Fałsz"),  # the word minimum stays for page text
    ],
)
def test_page_text_stays_strict(quote, text):
    assert find_quote(quote, text) is None


def test_the_question_itself_can_be_quoted():
    assert find_quote("Kibice idą bronić Trybunału przed Tuskiem?", TITLE)
