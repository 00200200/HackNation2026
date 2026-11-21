"""Justification text per verdict: built from the evidence, never from the extraction note."""

from datetime import UTC, date, datetime

from prawdowid import justification
from prawdowid.contract import Source, Verdict
from prawdowid.judge import Evidence, Label, Stance, decide

TODAY = date(2026, 11, 21)
CLAIM_NOTE = "Twierdzenie dotyczy konkretnego zdarzenia z podaną datą."


def source(
    publisher, text, published=date(2026, 7, 3), source_type="official", slug="a"
):
    return Source(
        title="Komunikat",
        publisher=publisher,
        published_at=published,
        fetched_at=datetime(2026, 11, 21, tzinfo=UTC),
        url=f"https://{slug}.gov.pl/x",
        source_type=source_type,
        fragment=text,
    )


def evidence(src, stance, **label):
    return Evidence(
        label=Label(doc_id=str(src.url), stance=stance, quote=src.fragment, **label),
        source=src,
        text=src.fragment,
        context_span=label.get("context_quote"),
    )


MON = source("MON", "Polska jest członkiem NATO od 1999 roku.")
KE = source("Komisja Europejska", "UE nie nakłada takiego podatku.", slug="b")


def decided(*items):
    judgement = decide(list(items), [], TODAY)
    return judgement.verdict, judgement.justification


def test_confirmed_names_publisher_date_and_quote():
    verdict, text = decided(evidence(MON, Stance.SUPPORTS))
    assert verdict is Verdict.CONFIRMED
    assert text == (
        "Potwierdza to: MON, 3.07.2026: „Polska jest członkiem NATO od 1999 roku.”."
    )


def test_false_cites_the_refuting_source_only():
    verdict, text = decided(evidence(MON, Stance.REFUTES), evidence(KE, Stance.CONTEXT))
    assert verdict is Verdict.FALSE
    assert text.startswith("Przeczy temu: MON, 3.07.2026: „Polska jest")
    assert "Komisja Europejska" not in text


def test_misleading_states_the_missing_context_and_its_source():
    verdict, text = decided(
        evidence(
            MON,
            Stance.CONTEXT,
            missing_context="dotyczy tylko 2024 roku",
            context_quote="Polska jest członkiem",
        )
    )
    assert verdict is Verdict.MISLEADING
    assert (
        text
        == "Twierdzenie pomija ważny kontekst: dotyczy tylko 2024 roku (MON, 3.07.2026: „Polska jest członkiem”)."
    )


def test_conflict_names_both_sides_and_does_not_decide():
    verdict, text = decided(
        evidence(MON, Stance.SUPPORTS), evidence(KE, Stance.REFUTES)
    )
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "potwierdza MON" in text and "przeczy Komisja Europejska" in text
    assert text.endswith("Nie rozstrzygamy, które ma rację.")


def test_insufficient_with_weak_evidence_says_how_little_was_found():
    weak = source("Portal A", "Ktoś pisze, że tak.", source_type="article", slug="c")
    verdict, text = decided(evidence(weak, Stance.SUPPORTS))
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert text.startswith("Znaleźliśmy za mało, żeby to rozstrzygnąć: Portal A")


def test_insufficient_without_sources_says_none_were_found():
    verdict, text = decided()
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert text == justification.NO_SOURCES


def test_data_gap_is_named():
    verdict, text = decided(evidence(MON, Stance.GAP, own_conclusion=True))
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert text == (
        "Źródła mówią, że dostępne dane nie pozwalają tego sprawdzić: MON, 3.07.2026."
    )


def test_not_checked_is_an_outage_not_a_verdict():
    text = justification.explain(Verdict.NOT_CHECKED, [])
    assert text.startswith("To nie jest ocena twierdzenia")
    assert "Nie mogliśmy go teraz sprawdzić" in text
    assert "dowod" not in text


def test_not_verifiable():
    text = justification.explain(Verdict.NOT_VERIFIABLE, [])
    assert "nie wydajemy oceny" in text


def test_long_quote_is_cut_at_a_word_and_undated_source_says_so():
    long = source("MON", "słowo " * 100, published=None)
    text = justification.explain(Verdict.CONFIRMED, [(long, "supports", None)])
    assert "MON, bez daty: „słowo" in text
    assert "…”" in text and len(text) < 260


def test_same_document_cited_once_and_extras_counted():
    docs = [source(f"P{i}", "x", slug=f"s{i}") for i in range(4)]
    text = justification.explain(
        Verdict.FALSE, [(d, "refutes", None) for d in docs + docs[:1]]
    )
    assert text.count("P0") == 1 and text.endswith("i jeszcze 2.")


def test_extraction_note_never_reaches_a_checked_claim():
    from prawdowid import pipeline, verifier
    from prawdowid.judge import Judgement

    claim = verifier.ExtractedClaim(
        claim="Polska wystąpiła z NATO w 2025 roku.",
        kind="statement",
        source_sentence="Polska wystąpiła z NATO w 2025 roku.",
        checkable=True,
        reason=CLAIM_NOTE,
        queries=[],
    )
    judgement = decide([evidence(MON, Stance.REFUTES)], [], TODAY)
    check = pipeline.ClaimCheck(judgement=judgement, cost_usd=0.0, steps_ms={})
    assert verifier.claim_result(claim, check).reasoning == judgement.justification
    outage = Judgement(
        verdict=Verdict.NOT_CHECKED,
        strength="brak",
        premises=[],
        sources=[],
        limitations=["x"],
    )
    out = pipeline.ClaimCheck(judgement=outage, cost_usd=0.0, steps_ms={})
    assert verifier.claim_result(claim, out).reasoning == justification.NOT_CHECKED
    # A claim that was never checked keeps the model's note: it says why.
    assert verifier.claim_result(claim, None).reasoning == CLAIM_NOTE


def test_publisher_whose_own_conclusion_is_a_gap_is_not_cited_as_confirming():
    # Its quote of the claim confirms nothing (decide drops it); Portal A is the real support.
    quoter = source("Fact-checker", "Twierdzenie: Polska wyszła z NATO.", slug="q")
    support = source("Portal A", "Polska jest w NATO.", source_type="article", slug="c")
    support2 = source("Portal B", "NATO liczy Polskę.", source_type="article", slug="d")
    verdict, text = decided(
        evidence(quoter, Stance.SUPPORTS),
        evidence(quoter, Stance.GAP, own_conclusion=True),
        evidence(support, Stance.SUPPORTS),
        evidence(support2, Stance.SUPPORTS),
    )
    assert verdict is Verdict.CONFIRMED
    assert "Fact-checker" not in text and "Portal A" in text


def test_two_weak_sources_on_opposite_sides_are_not_called_a_conflict():
    a = source("Portal A", "Tak.", source_type="article", slug="c")
    b = source("Portal B", "Nie.", source_type="article", slug="d")
    verdict, text = decided(evidence(a, Stance.SUPPORTS), evidence(b, Stance.REFUTES))
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert text.startswith("Znaleźliśmy za mało")
    assert "sprzeczne" not in text and "Wiarygodne" not in text


def test_self_contradicting_publisher_dropped_by_decide_is_not_cited():
    both = source("Portal A", "Raz tak, raz nie.", source_type="article", slug="c")
    verdict, text = decided(
        evidence(both, Stance.SUPPORTS), evidence(both, Stance.REFUTES)
    )
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "potwierdza Portal A, przeczy Portal A" not in text


def test_evidence_that_no_side_counts_is_still_named_not_called_absent():
    # Context label without a verified context quote: nothing counts, but the source exists.
    ctx = source("Portal A", "Inne czasy.", source_type="article", slug="c")
    verdict, text = decided(evidence(ctx, Stance.CONTEXT))
    assert verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert text.startswith("Znaleźliśmy za mało") and "Portal A" in text
