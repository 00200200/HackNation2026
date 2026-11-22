"""The catalogue, the build orchestration and the requirement checks of the brief."""

import json
from datetime import date

import pytest

from corpus import build as build_module
from corpus.build import build, run_source
from corpus.catalog import Catalog, RemovedUrl, load_catalog
from corpus.check import (
    DOCS_PATH,
    MAX_BYTES,
    MIN_DOCS,
    MIN_DOMAINS,
    problems,
    summarize,
)
from corpus.http import Blocked
from corpus.schema import (
    PRIMARY_TYPES,
    SECONDARY_TYPES,
    Doc,
    doc_id,
    mask_personal,
    read_jsonl,
    write_jsonl,
)
from corpus.sources import COLLECTORS
from corpus.sources.base import Stopped, make_doc
from tests.corpus_helpers import offline_client, source

REQUIRED_FIELDS = (
    "id",
    "url",
    "title",
    "publisher",
    "published_at",
    "retrieved_at",
    "source_type",
    "licence",
    "language",
    "text",
)


def doc(source_id: str, url: str, **overrides) -> Doc:
    fields = {
        "id": doc_id(source_id, url),
        "url": url,
        "title": "Tytuł",
        "publisher": "Urząd",
        "published_at": "2026-11-20",
        "retrieved_at": "2026-11-21T15:00:00+00:00",
        "source_type": "official",
        "licence": "CC BY-SA 4.0",
        "language": "pl",
        "text": "Treść komunikatu.",
        "source_id": source_id,
        "storage": "full_text",
    }
    return Doc(**{**fields, **overrides})


# -- catalogue -----------------------------------------------------------------------------------


def test_catalogue_is_valid_and_every_active_source_has_a_collector():
    catalog = load_catalog()
    active = [s for s in catalog.sources if s.status == "active"]
    assert active and all(s.collector in COLLECTORS for s in active)
    assert {"admit", "storage", "update", "exclude"} <= set(catalog.rules)
    excluded = [s for s in catalog.sources if s.status == "excluded"]
    assert excluded and all(s.excluded_on and s.excluded_reason for s in excluded)
    assert all(s.licence_checked for s in active if not s.requires_env)


def test_catalogue_covers_both_source_types_without_any_key():
    keyless = [
        s for s in load_catalog().sources if s.status == "active" and not s.requires_env
    ]
    types = {s.source_type for s in keyless}
    assert types & PRIMARY_TYPES and types & SECONDARY_TYPES
    assert len({s.registered_domain for s in keyless}) >= MIN_DOMAINS


def test_catalogue_rejects_incomplete_entries():
    with pytest.raises(ValueError, match="excluded_on"):
        source(status="excluded")
    with pytest.raises(ValueError, match="collector"):
        source(collector=None)
    with pytest.raises(ValueError, match="note"):
        source(status="candidate")
    rules = {"admit": ["x"]}
    with pytest.raises(ValueError, match="duplicate"):
        Catalog(rules=rules, sources=[source(), source()])


# -- build ---------------------------------------------------------------------------------------


@pytest.fixture
def fake_collectors(monkeypatch):
    def install(**collectors):
        monkeypatch.setattr(build_module, "COLLECTORS", collectors)

    return install


def test_build_merges_sources_drops_duplicates_and_removed_urls(fake_collectors):
    fake_collectors(
        first=lambda s, c: [
            doc(s.id, "https://a.gov.pl/1"),
            doc(s.id, "https://a.gov.pl/2"),
        ],
        second=lambda s, c: [
            doc(s.id, "https://a.gov.pl/2"),
            doc(s.id, "https://b.pl/3"),
        ],
    )
    catalog = Catalog(
        rules={"admit": ["x"]},
        removed_urls=[
            RemovedUrl(
                url="https://b.pl/3", reason="correction", removed_on=date(2026, 11, 21)
            )
        ],
        sources=[
            source(id="one", collector="first"),
            source(id="two", collector="second"),
            source(
                id="gone",
                status="excluded",
                collector=None,
                excluded_on=date(2026, 11, 21),
                excluded_reason="robots.txt",
            ),
        ],
    )
    docs, rows = build(catalog, offline_client({}))
    assert sorted(d.url for d in docs) == ["https://a.gov.pl/1", "https://a.gov.pl/2"]
    assert [d.source_id for d in docs if d.url.endswith("/2")] == [
        "one"
    ]  # first entry wins
    by_id = {r["id"]: r for r in rows}
    assert (by_id["one"]["documents"], by_id["two"]["documents"]) == (2, 0)
    assert by_id["gone"]["note"] == "robots.txt"


def test_one_failing_source_does_not_stop_the_others(fake_collectors):
    def blocked(s, c):
        raise Blocked("robots.txt disallows this path")

    def crashing(s, c):
        raise KeyError("layout changed")

    fake_collectors(
        good=lambda s, c: [doc(s.id, "https://a.gov.pl/1")],
        blocked=blocked,
        bad=crashing,
    )
    catalog = Catalog(
        rules={"admit": ["x"]},
        sources=[
            source(id="ok", collector="good"),
            source(id="blocked", collector="blocked"),
            source(id="broken", collector="bad"),
        ],
    )
    docs, rows = build(catalog, offline_client({}))
    notes = {r["id"]: r["note"] for r in rows}
    assert len(docs) == 1
    assert notes["blocked"] == "blocked: robots.txt disallows this path"
    assert notes["broken"].startswith("failed: KeyError")


def test_source_without_its_key_is_skipped_with_a_clear_note(
    monkeypatch, fake_collectors
):
    def must_not_run(s, c):
        raise AssertionError("the collector ran without its key")

    fake_collectors(keyed=must_not_run)
    monkeypatch.delenv("PRAWDOWID_TEST_KEY", raising=False)
    needs_key = source(collector="keyed", requires_env="PRAWDOWID_TEST_KEY")
    assert run_source(needs_key, offline_client({})) == (
        [],
        "skipped: PRAWDOWID_TEST_KEY is not set",
    )


def test_rebuilding_one_source_keeps_the_documents_of_the_others(fake_collectors):
    fake_collectors(
        first=lambda s, c: [doc(s.id, "https://a.gov.pl/new")],
        second=lambda s, c: [doc(s.id, "https://b.pl/never-called")],
    )
    catalog = Catalog(
        rules={"admit": ["x"]},
        sources=[
            source(id="one", collector="first"),
            source(id="two", collector="second"),
        ],
    )
    previous = [doc("one", "https://a.gov.pl/old"), doc("two", "https://b.pl/kept")]
    docs, rows = build(catalog, offline_client({}), only={"one"}, previous=previous)
    assert sorted(d.url for d in docs) == ["https://a.gov.pl/new", "https://b.pl/kept"]
    assert {r["id"]: r["note"] for r in rows}[
        "two"
    ] == "not rebuilt, kept from the previous build"


def test_a_failing_source_keeps_its_records_from_the_previous_build(fake_collectors):
    def blocked(s, c):
        raise Blocked("HTTP 429: site refuses automated clients")

    fake_collectors(blocked=blocked)
    catalog = Catalog(
        rules={"admit": ["x"]}, sources=[source(id="one", collector="blocked")]
    )
    previous = [doc("one", "https://a.gov.pl/1"), doc("gone", "https://b.pl/2")]
    docs, rows = build(catalog, offline_client({}), previous=previous)
    assert [d.url for d in docs] == [
        "https://a.gov.pl/1"
    ]  # records of removed sources go
    assert rows[0]["note"] == (
        "blocked: HTTP 429: site refuses automated clients; kept 1 records from the previous build"
    )


def test_a_source_blocked_part_way_adds_its_older_records(fake_collectors):
    def stopped(s, c):
        raise Stopped(
            "HTTP 429: site refuses automated clients", [doc(s.id, "https://a.pl/new")]
        )

    fake_collectors(stopped=stopped)
    catalog = Catalog(
        rules={"admit": ["x"]}, sources=[source(id="one", collector="stopped")]
    )
    previous = [
        doc("one", "https://a.pl/new", title="stary"),
        doc("one", "https://a.pl/old"),
    ]
    docs, rows = build(catalog, offline_client({}), previous=previous)
    assert sorted(d.url for d in docs) == ["https://a.pl/new", "https://a.pl/old"]
    assert [d.title for d in docs if d.url.endswith("new")] == [
        "Tytuł"
    ]  # the new copy wins
    assert rows[0]["note"].startswith("stopped after 1 records: HTTP 429")
    assert rows[0]["note"].endswith("; kept 1 records from the previous build")


def test_missing_key_keeps_records_but_a_snapshot_does_not(
    monkeypatch, fake_collectors
):
    def blocked(s, c):
        raise Blocked("HTTP 403: site refuses automated clients")

    fake_collectors(keyed=lambda s, c: [], blocked=blocked)
    monkeypatch.delenv("PRAWDOWID_TEST_KEY", raising=False)
    catalog = Catalog(
        rules={"admit": ["x"]},
        sources=[
            source(id="google", collector="keyed", requires_env="PRAWDOWID_TEST_KEY"),
            source(id="imgw", collector="blocked", params={"snapshot": True}),
        ],
    )
    previous = [
        doc("google", "https://g.pl/1"),
        doc("imgw", "https://imgw.pl/old-warning"),
    ]
    docs, rows = build(catalog, offline_client({}), previous=previous)
    assert [d.url for d in docs] == ["https://g.pl/1"]
    assert rows[1]["note"] == "blocked: HTTP 403: site refuses automated clients"


def test_main_writes_nothing_when_a_threshold_is_missed(
    monkeypatch, tmp_path, fake_collectors
):
    def few(s, c):
        build_module.log.warning("%s: skipped https://a.pl/x (HTTP 404)", s.id)
        return [doc(s.id, "https://a.gov.pl/1")]

    fake_collectors(few=few)
    catalog = Catalog(
        rules={"admit": ["x"]}, sources=[source(id="one", collector="few")]
    )
    monkeypatch.setattr(build_module, "load_catalog", lambda: catalog)
    monkeypatch.setattr(build_module, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(build_module, "CACHE_DIR", tmp_path / "cache")
    out = tmp_path / "docs.jsonl"
    write_jsonl([doc("gone", "https://b.pl/old")], out)
    before = out.read_text()
    assert build_module.main(["--out", str(out)]) == 1
    assert out.read_text() == before and not (tmp_path / "manifest.json").exists()
    assert not list(tmp_path.glob("*.draft.jsonl"))

    out.unlink()
    assert (
        build_module.main(["--out", str(out), "--force"]) == 1
    )  # written, still failing
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [d.url for d in read_jsonl(out)] == ["https://a.gov.pl/1"]
    assert manifest["sources"][0]["warnings"] == 1
    assert manifest["sources"][0]["first_warnings"] == [
        "skipped https://a.pl/x (HTTP 404)"
    ]


def test_a_source_that_returns_nothing_keeps_its_older_records(fake_collectors):
    fake_collectors(empty=lambda s, c: [])
    catalog = Catalog(
        rules={"admit": ["x"]}, sources=[source(id="one", collector="empty")]
    )
    docs, rows = build(
        catalog, offline_client({}), previous=[doc("one", "https://a.pl/1")]
    )
    assert [d.url for d in docs] == ["https://a.pl/1"]
    assert rows[0]["note"] == "no documents; kept 1 records from the previous build"


def test_job_adverts_are_not_kept():
    advert = make_doc(
        source(),
        url="https://www.gov.pl/web/kgpsp/nabor",
        title="Nabór w ramach przeniesienia służbowego do Biura Kadr KG PSP",
        text="Osoby do kontaktu: ...",
        published_at=None,
        retrieved_at="2026-11-21T15:00:00+00:00",
    )
    assert advert is None


# -- requirement checks ----------------------------------------------------------------------------


def passing_docs() -> list[Doc]:
    docs = [doc("s", f"https://site{n % 10}.pl/{n}") for n in range(MIN_DOCS)]
    docs[0] = doc("f", "https://site0.pl/0", source_type="fact_checker")
    return docs


def test_checks_pass_on_a_corpus_that_meets_the_brief():
    assert problems(passing_docs(), size_bytes=1000) == []
    summary = summarize(passing_docs())
    assert summary["documents"] == MIN_DOCS
    assert len(summary["registered_domains"]) == MIN_DOMAINS


def test_checks_name_every_missed_threshold():
    few = [doc("s", f"https://www.gov.pl/web/unit{n}/news") for n in range(20)]
    found = problems(few, size_bytes=MAX_BYTES)
    assert f"20 documents, need at least {MIN_DOCS}" in found
    assert (
        f"1 registered domains, need at least {MIN_DOMAINS}" in found
    )  # subpages: one domain
    assert "no reliable secondary source (fact-checker or incident base)" in found
    assert any("push limit" in p for p in found)


def test_checks_catch_personal_data_long_excerpts_and_duplicates():
    digits = "4405140135"
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    pesel = digits + str(
        (10 - sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 10) % 10
    )
    docs = passing_docs() + [
        doc("s", "https://x.pl/mail", text="Kontakt: jan.kowalski@example.pl"),
        doc("s", "https://x.pl/pesel", text=f"PESEL {pesel} w treści"),
        doc("s", "https://x.pl/long", storage="excerpt", text="a" * 600),
        doc("s", "https://x.pl/dup"),
        doc("s", "https://x.pl/dup"),
    ]
    found = " | ".join(problems(docs, banned=set()))
    assert "e-mail address" in found
    assert "looks like a PESEL" in found
    assert "excerpt has 600 characters" in found
    assert "repeated url" in found
    assert "12345678901" not in found
    assert (
        problems(passing_docs() + [doc("s", "https://x.pl/n", text="nr 12345678901")])
        == []
    )


def test_committed_corpus_meets_the_brief():
    """Brief, section 5: at least 100 documents or records, 10 domains and two source types,
    with publication and retrieval timestamps. Runs on the file the product ships with."""
    assert DOCS_PATH.exists(), "run `make corpus` to build corpus/evidence.jsonl"
    docs = read_jsonl(DOCS_PATH)
    assert problems(docs, DOCS_PATH.stat().st_size) == []
    summary = summarize(docs)
    assert summary["documents"] >= MIN_DOCS
    assert len(summary["registered_domains"]) >= MIN_DOMAINS
    assert set(summary["source_types"]) & PRIMARY_TYPES
    assert set(summary["source_types"]) & SECONDARY_TYPES
    assert all(d.retrieved_at for d in docs)
    assert all(set(REQUIRED_FIELDS) <= set(d.model_dump()) for d in docs[:5])
    active = {s.id: s for s in load_catalog().sources if s.status == "active"}
    assert {d.source_id for d in docs} <= set(active), (
        "documents from a source that is not active"
    )
    assert all(d.licence == active[d.source_id].licence for d in docs)


def test_checks_refuse_contact_persons_and_disinformation_domains():
    docs = passing_docs() + [
        doc("s", "https://x.pl/job", text="Osoby do kontaktu: tel. 22 000 00 00"),
        doc("s", "https://news.example-outlet.ru/a"),
    ]
    found = " | ".join(problems(docs, banned={"example-outlet.ru"}))
    assert "names contact persons" in found
    assert "from a domain on the disinformation list" in found


def test_checks_name_the_record_with_an_unmasked_identifier():
    docs = passing_docs() + [
        doc("s", "https://x.pl/tel", text="Kontakt: tel.600123456"),
        doc("s", "https://x.pl/plus", title="Infolinia +48 22 279 99 99"),
        doc(
            "s",
            "https://x.pl/ok",
            text="Kontakt: tel. [telefon], [adres e-mail usunięty]",
        ),
    ]
    found = problems(docs, banned=set())
    assert (
        f"{doc_id('s', 'https://x.pl/tel')}: unmasked personal identifier in text"
        in found
    )
    assert (
        f"{doc_id('s', 'https://x.pl/plus')}: unmasked personal identifier in title"
        in found
    )
    assert not any(doc_id("s", "https://x.pl/ok") in p for p in found)


def test_mask_personal_hides_phones_and_emails_but_keeps_names():
    text = "Rzecznik Jan Kowalski, jan@example.pl, tel.600123456, infolinia +48 22 279 99 99"
    masked = mask_personal(text)
    assert masked == (
        "Rzecznik Jan Kowalski, [adres e-mail usunięty], tel.[telefon], infolinia [telefon]"
    )
    assert mask_personal(masked) == masked


def test_the_builder_masks_before_writing(tmp_path):
    made = make_doc(
        source(),
        url="https://www.gov.pl/web/x/prasowy",
        title="Kontakt tel. 600 123 456",
        text="Rzecznik: tel.600123456, jan@example.pl",
        published_at=None,
        retrieved_at="2026-11-21T15:00:00+00:00",
        claim="Zadzwoń +48 600 100 200",
    )
    write_jsonl([made], tmp_path / "e.jsonl")
    written = (tmp_path / "e.jsonl").read_text(encoding="utf-8")
    assert (
        "600123" not in written
        and "example.pl" not in written
        and "600 100" not in written
    )
    assert not any("personal identifier" in p for p in problems([made], banned=set()))


def test_an_excerpt_is_masked_after_its_lines_are_joined():
    made = make_doc(
        source(storage="excerpt"),
        url="https://example.gov.pl/a",
        title="T",
        text="Kontakt: 600 100\n200",
        published_at=None,
        retrieved_at="2026-11-21T15:00:00+00:00",
    )
    assert made.text == "Kontakt: [telefon]"
    assert not any("identifier" in p for p in problems([made], banned=set()))


def test_a_masked_passport_does_not_hide_a_phone_from_the_masking():
    assert mask_personal("Paszport AB1234567 600 123 456") == (
        "Paszport [numer paszportu] [telefon]"
    )


def test_a_rating_is_masked():
    made = make_doc(
        source(),
        url="https://x.pl/r",
        title="T",
        text="Tekst",
        published_at=None,
        retrieved_at="2026-11-21T15:00:00+00:00",
        claim="Twierdzenie",
        rating="Fałsz, tel. 600 100 200",
    )
    assert made.rating == "Fałsz, tel. [telefon]"
