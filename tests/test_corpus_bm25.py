"""The BM25 lookup in the evidence corpus, offline: the real corpus file and small corpora
written per test. No key, no network, no model."""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import pytest

from prawdowid import corpus_bm25, factcheck, pipeline, websearch

# The conftest replaces the module's `search_evidence` with an empty lookup in every test.
REAL_SEARCH_EVIDENCE = corpus_bm25.search_evidence


def record(
    url="https://www.gov.pl/a", title="Tytuł", text="Treść dokumentu.", **fields
):
    return {
        "url": url,
        "title": title,
        "publisher": "Ministerstwo Testowe",
        "published_at": "2026-10-28",
        "retrieved_at": "2026-11-21T21:40:35+00:00",
        "source_type": "official",
        "text": text,
        **fields,
    }


@pytest.fixture
def corpus(monkeypatch, tmp_path):
    """Writes a corpus file (the records, or `raw` text or bytes), points the module at it and
    returns the lookup over it."""
    path = tmp_path / "evidence.jsonl"
    monkeypatch.setattr(corpus_bm25, "CORPUS_PATH", path)

    def write(*records, raw=None):
        if raw is None:
            raw = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        path.write_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
        return corpus_bm25._search

    return write


@pytest.fixture(scope="module")
def stored():
    """The real corpus file, record by URL."""
    lines = corpus_bm25.CORPUS_PATH.read_text(encoding="utf-8").splitlines()
    return {r["url"]: r for r in map(json.loads, lines)}


def urls(found):
    return [str(h.source.url) for h in found.hits]


# -- the real corpus ----------------------------------------------------------------------------


def test_a_country_in_odyseusz_returns_its_profile_with_the_date(stored):
    found = corpus_bm25._search(["Czy MSZ odradza podróże do Izraela?"])
    top = found.hits[0].source
    saved = stored[str(top.url)]
    assert top.title.startswith("Izrael") and "Odyseusz" in top.publisher
    assert top.published_at == date.fromisoformat(saved["published_at"][:10])
    assert top.fetched_at == datetime.fromisoformat(saved["retrieved_at"])
    assert top.source_type == "official" and found.limitation is None


def test_the_fragment_is_a_verbatim_part_of_the_document(stored):
    found = corpus_bm25._search(["Czy MSZ odradza podróże do Izraela?"])
    for hit in found.hits:
        passages = hit.source.fragment.split("\n\n")
        assert all(p in stored[str(hit.source.url)]["text"] for p in passages)


@pytest.mark.parametrize(
    "claim, publisher",
    [
        ("Czy MSZ odradza podróże do Izraela?", "Odyseusz"),
        ("SMS o dopłacie do paczki to oszustwo CERT Polska", "CERT Polska"),
        ("IMGW ostrzega przed suszą hydrologiczną", "Meteorologii"),
        ("Czy w Polsce jest wysoka inflacja według GUS?", "Statystyczny"),
    ],
)
def test_claims_find_the_documents_of_their_domain(claim, publisher):
    found = corpus_bm25._search([claim])
    assert publisher in found.hits[0].source.publisher
    # A few documents, a few passages of each, every document once.
    assert len(found.hits) <= corpus_bm25.MAX_DOCS
    assert len(set(urls(found))) == len(found.hits)
    assert all(
        len(h.source.fragment.split("\n\n")) <= corpus_bm25.PER_DOC for h in found.hits
    )


def test_step_2_of_a_check_finds_the_profile_of_the_country(monkeypatch, stored):
    """The lookup is wired into `_retrieve`: the profile arrives with the other sources, and its
    time goes to the check log."""
    monkeypatch.setattr(corpus_bm25, "search_evidence", REAL_SEARCH_EVIDENCE)

    async def no_pages(query, **kwargs):
        return websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE)

    monkeypatch.setattr(websearch, "search_web", no_pages)
    steps, found = {}, {"web": []}
    claim = "Czy MSZ odradza podróże do Izraela?"
    asyncio.run(pipeline._retrieve(claim, ["MSZ Izrael podróże"], None, steps, found))
    top = found["corpus"].hits[0].source
    assert top.title.startswith("Izrael")
    assert top in pipeline._candidates(found)
    assert isinstance(steps["corpus"], int)


# -- a corpus that cannot be used ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "to nie jest JSON\n",
        '{"title": "Bez adresu", "text": "Egipt."}\n',  # no usable record
    ],
)
def test_a_corpus_without_usable_records_is_a_limitation(corpus, raw):
    found = corpus(raw=raw)(["Egipt"])
    assert found.hits == [] and found.limitation == corpus_bm25.CORPUS_UNAVAILABLE


def test_a_missing_corpus_is_a_limitation(monkeypatch, tmp_path):
    monkeypatch.setattr(corpus_bm25, "CORPUS_PATH", tmp_path / "none.jsonl")
    found = corpus_bm25._search(["Egipt"])
    assert found.hits == [] and found.limitation == corpus_bm25.CORPUS_UNAVAILABLE


def test_a_corpus_that_is_not_text_is_a_limitation(monkeypatch, tmp_path):
    path = tmp_path / "evidence.jsonl"
    path.write_bytes(b"\xff\xfe\x00")
    monkeypatch.setattr(corpus_bm25, "CORPUS_PATH", path)
    assert corpus_bm25._search(["Egipt"]).limitation == corpus_bm25.CORPUS_UNAVAILABLE


def test_a_corpus_that_comes_back_is_searched_without_a_restart(corpus):
    search = corpus(raw="")
    assert search(["Egipt"]).limitation == corpus_bm25.CORPUS_UNAVAILABLE
    search = corpus(record(text="Egipt: ostrzeżenie."))
    assert len(search(["Egipt"]).hits) == 1


def test_unusable_records_are_skipped_the_rest_is_served(corpus):
    search = corpus(
        record(url="not a url", text="Egipt."),
        record(published_at="jutro", text="Egipt."),
        {"title": "Bez tekstu", "url": "https://www.gov.pl/b"},
        record(url="https://www.gov.pl/dobry", text="Egipt: ostrzeżenie."),
    )
    found = search(["Egipt"])
    assert urls(found) == ["https://www.gov.pl/dobry"] and found.limitation is None


def test_a_line_that_is_no_record_is_skipped_the_rest_is_served(corpus):
    good = json.dumps(record(text="Egipt: ostrzeżenie."), ensure_ascii=False)
    # Cut JSON, a JSON array, a line that is no UTF-8.
    raw = b'{"urwany": \n' + good.encode() + b"\n[1, 2]\n\xff\xfe\n"
    found = corpus(raw=raw)(["Egipt"])
    assert urls(found) == ["https://www.gov.pl/a"] and found.limitation is None


def test_a_line_separator_inside_a_text_does_not_cut_the_record(corpus):
    found = corpus(record(text="Egipt: ostrzeżenie."))(["Egipt"])
    assert [h.source.fragment for h in found.hits] == ["Egipt: ostrzeżenie."]


def test_a_record_with_fields_of_the_wrong_type_does_not_fail_the_build(corpus):
    search = corpus(
        record(url="https://www.gov.pl/a", rating=3, claim=["x"], text="Egipt: a."),
        record(
            url="https://www.gov.pl/b", rating="Fałsz", claim={"x": 1}, text="Egipt: b."
        ),
        record(url="https://www.gov.pl/c", text="Egipt: c."),
    )
    fragments = {str(h.source.url): h.source.fragment for h in search(["Egipt"]).hits}
    assert fragments == {
        "https://www.gov.pl/a": "Egipt: a.",  # no rating: the text itself
        "https://www.gov.pl/b": factcheck.review_fragment("Fałsz", None),  # no claim
        "https://www.gov.pl/c": "Egipt: c.",
    }


# -- what a hit says about its document ---------------------------------------------------------


@pytest.mark.parametrize(
    "published, expected",
    [
        ("2026-10-28", date(2026, 10, 28)),
        ("2026-09-07T10:31:58+00:00", date(2026, 9, 7)),
        (None, None),
    ],
)
def test_the_publication_date_comes_from_the_record(corpus, published, expected):
    source = (
        corpus(record(published_at=published, text="Egipt."))(["Egipt"]).hits[0].source
    )
    assert source.published_at == expected
    assert source.fetched_at == datetime.fromisoformat("2026-11-21T21:40:35+00:00")


def test_a_fact_checker_is_a_fact_check_source_to_the_judge(corpus):
    source = (
        corpus(
            record(
                source_type="fact_checker",
                publisher="Pravda",
                text="Szczepionki: wyjaśniamy.",
            )
        )(["szczepionki"])
        .hits[0]
        .source
    )
    assert source.source_type == "fact_check" and source.publisher == "Pravda"
    assert source.fragment == "Szczepionki: wyjaśniamy."


def test_a_rating_reaches_the_judge_as_a_rating_never_as_the_claim_alone(corpus):
    claim = "Szczepionki powodują autyzm"
    source = (
        corpus(
            record(
                title="Szczepionki a autyzm",
                source_type="fact_checker",
                publisher="Demagog",
                text=f"Ocena (Demagog): Fałsz. Sprawdzane twierdzenie: „{claim}”",
                claim=claim,
                rating="Fałsz",
            )
        )(["szczepionki autyzm"])
        .hits[0]
        .source
    )
    assert source.fragment == factcheck.review_fragment("Fałsz", claim)
    assert source.fragment.startswith(factcheck.RATING_PREFIX)


# -- ranking ------------------------------------------------------------------------------------


def test_ranking_ignores_stopwords(corpus):
    search = corpus(
        record(
            url="https://www.gov.pl/egipt",
            title="Egipt",
            text="Egipt: ostrzeżenie dla podróżujących.",
        ),
        record(
            url="https://www.gov.pl/stopwords",
            title="Pytanie",
            text="Czy jest tak, że nie jest, ale jest i czy nie jest, jednak jest.",
        ),
    )
    assert search(["czy jest tak że nie jest"]).hits == []  # nothing but stopwords
    plain = urls(search(["ostrzeżenie Egipt"]))
    padded = urls(search(["czy jest ostrzeżenie dla Egiptu oraz nie jest"]))
    assert plain == padded == ["https://www.gov.pl/egipt"]


@pytest.mark.parametrize("query", ["Łódź", "lodz", "ŁÓDŹ"])
def test_case_and_diacritics_do_not_matter(corpus, query):
    found = corpus(record(text="Burza nad miastem. Łódź: ostrzeżenie."))(query.split())
    assert len(found.hits) == 1


def test_inflected_forms_meet(corpus):
    assert len(corpus(record(text="Strajków nie będzie."))(["strajku"]).hits) == 1


def test_a_title_that_names_the_subject_ranks_its_document_first(corpus):
    """Same passage in both documents: the one whose title names the country wins."""
    text = "Wizy. Izrael wspomniany raz."
    search = corpus(
        record(url="https://www.gov.pl/other", title="Ogólne", text=text),
        record(url="https://www.gov.pl/izrael", title="Izrael – informacje", text=text),
    )
    assert urls(search(["Izrael"])) == [
        "https://www.gov.pl/izrael",
        "https://www.gov.pl/other",
    ]


def test_a_word_found_everywhere_matches_nothing(corpus):
    filler = [
        record(
            url=f"https://www.gov.pl/{i}",
            title=f"Dokument {i}",
            text="Ogólne informacje o urzędzie.",
        )
        for i in range(120)
    ]
    search = corpus(
        *filler, record(url="https://www.gov.pl/egipt", title="Egipt", text="Egipt.")
    )
    assert search(["ogólne informacje"]).hits == []
    assert urls(search(["Egipt"])) == ["https://www.gov.pl/egipt"]


def test_every_query_adds_its_documents(corpus):
    search = corpus(
        record(
            url="https://www.gov.pl/egipt", title="Egipt", text="Egipt: ostrzeżenie."
        ),
        record(url="https://www.gov.pl/peru", title="Peru", text="Peru: szczepienia."),
    )
    assert set(urls(search(["Egipt", "Peru"]))) == {
        "https://www.gov.pl/egipt",
        "https://www.gov.pl/peru",
    }


def test_few_documents_and_few_passages_of_each(corpus, monkeypatch):
    monkeypatch.setattr(
        corpus_bm25, "RARE_FLOOR", 100
    )  # in this tiny corpus every word is rare
    line = ("kometa leci nad miastem " * 30)[:700]  # two lines never fit one passage
    docs = [
        record(
            url=f"https://www.gov.pl/{i}", title=f"Nr {i}", text="\n".join([line] * 4)
        )
        for i in range(8)
    ]
    found = corpus(*docs)(["kometa"])
    assert len(found.hits) == corpus_bm25.MAX_DOCS
    assert all(
        len(h.source.fragment.split("\n\n")) == corpus_bm25.PER_DOC for h in found.hits
    )


def test_the_words_of_a_text_are_folded_stemmed_and_without_stopwords():
    assert corpus_bm25.terms("Łódź i okolice, czy jest strajków") == [
        "lodz",
        "okoli",
        "straj",
    ]


# -- the index ----------------------------------------------------------------------------------


def test_concurrent_first_lookups_build_the_index_once(corpus, monkeypatch):
    search = corpus(record(text="Egipt: ostrzeżenie."))
    built = []
    build = corpus_bm25._build

    def slow_build(path):
        built.append(path)
        time.sleep(0.2)
        return build(path)

    monkeypatch.setattr(corpus_bm25, "_build", slow_build)
    with ThreadPoolExecutor(6) as pool:
        found = list(pool.map(lambda _: search(["Egipt"]), range(6)))
    assert len(built) == 1 and all(len(f.hits) == 1 for f in found)


def test_the_async_lookup_searches_off_the_event_loop(corpus, monkeypatch):
    search = corpus(record(text="Egipt: ostrzeżenie."))
    threads = []

    def spy(queries):
        threads.append(threading.current_thread())
        return search(queries)

    monkeypatch.setattr(corpus_bm25, "_search", spy)
    found = asyncio.run(REAL_SEARCH_EVIDENCE(["Egipt"]))
    assert len(found.hits) == 1
    assert threads and threads[0] is not threading.main_thread()
