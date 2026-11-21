"""Steps 2 to 5 per claim, offline: fake search, FunctionModel rerank, judge and extraction."""

import asyncio
import re
import time
from datetime import UTC, date, datetime

import pytest
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from prawdowid import judge, pipeline, rerank, verifier, websearch
from prawdowid.cache import Document
from prawdowid.contract import ClaimKind, Verdict
from prawdowid.verifier import ExtractedClaim, Extraction

QUOTE = "Rząd potwierdza to w oficjalnym komunikacie."
USAGE = RequestUsage(input_tokens=1000, output_tokens=100)
OPUS, HAIKU, SONNET = (
    float(ModelResponse(parts=[], usage=USAGE, model_name=m).cost().total_price)
    for m in ("claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-5-5")
)


def document(url: str) -> Document:
    return Document(
        url=url,
        title="Komunikat",
        publisher="Ministerstwo",
        published_at=date.today(),
        fetched_at=datetime.now(UTC),
        source_type="official",
        domain="gov.pl",
        text=f"Wstęp. {QUOTE}",
    )


def fake_search(monkeypatch, delay=0.0, slow_word=None, found=lambda q: True):
    """Every query that `found` accepts returns one official page per query."""
    seen = []

    async def search(query, **kwargs):
        seen.append(query)
        await asyncio.sleep(60 if slow_word and slow_word in query else delay)
        if not found(query):
            return websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE)
        slug = re.sub(r"\W+", "-", query.casefold())
        return websearch.WebSearch(documents=[document(f"https://www.gov.pl/{slug}")])

    monkeypatch.setattr(websearch, "search_web", search)
    return seen


def model(answer, model_name="claude-haiku-5-5"):
    return FunctionModel(
        lambda messages, info: ModelResponse(
            parts=[TextPart(answer(messages[0].parts[-1].content))], usage=USAGE
        ),
        model_name=model_name,
    )


def every_fragment(prompt: str) -> str:
    return '{"ids": [0, 1, 2, 3, 4, 5]}'


def supports_all(prompt: str) -> str:
    labels = [
        {"doc_id": d, "stance": "supports", "quote": QUOTE, "missing_context": None}
        for d in re.findall(r"doc_id: (\S+)", prompt)
    ]
    return judge.Labels(labels=labels).model_dump_json()


@pytest.fixture
def models():
    with (
        rerank.agent.override(model=model(every_fragment)),
        judge.agent.override(model=model(supports_all, "claude-sonnet-5-5")),
    ):
        yield


def claims(n: int, slow: int | None = None) -> Extraction:
    def one(i):
        word = "wolne" if i == slow else "szybkie"
        return ExtractedClaim(
            claim=f"Twierdzenie {i}.",
            kind=ClaimKind.STATEMENT,
            source_sentence=f"Twierdzenie {i}.",
            checkable=True,
            reason="Fakt.",
            queries=[f"{word} {i} a", f"{word} {i} b", f"{word} {i} c"],
        )

    return Extraction(claims=[one(i) for i in range(n)], other_claims=[], unclear=False)


def verify(text: str, extraction: Extraction):
    with verifier.agent.override(
        model=model(lambda _: extraction.model_dump_json(), "claude-opus-5-5")
    ):
        return asyncio.run(verifier.verify(text))


def test_five_claims_with_fast_sources_finish_under_budget(monkeypatch, models):
    seen = fake_search(monkeypatch, delay=0.2)
    started = time.perf_counter()
    result = verify("tekst", claims(5))
    elapsed = time.perf_counter() - started
    assert [c.verdict for c in result.claims] == [Verdict.CONFIRMED] * 5
    assert len(seen) == 15
    # 15 searches of 0.2 s each: parallel, not one after another.
    assert elapsed < 1.5 < pipeline.CHECK_BUDGET_S
    assert {s.fragment for c in result.claims for s in c.sources} == {QUOTE}
    # Extraction (opus) plus rerank (haiku) and judge (sonnet) for each claim.
    assert result.cost_usd == pytest.approx(OPUS + 5 * (HAIKU + SONNET))
    # The check log gets every model answer with its tokens, and the time of each step.
    assert [m.model for m in result.model_calls].count("claude-sonnet-5-5") == 5
    assert len(result.model_calls) == 11 and result.model_calls[0].input_tokens == 1000
    assert {"rerank", "judge"} <= set(result.claims[0].steps_ms)


def test_slow_search_leaves_the_late_claim_not_checked(monkeypatch, models):
    monkeypatch.setattr(pipeline, "CHECK_BUDGET_S", 1.0)
    fake_search(monkeypatch, slow_word="wolne")
    started = time.perf_counter()
    result = verify("tekst", claims(3, slow=2))
    assert time.perf_counter() - started < 2
    fast, _, late = result.claims
    assert fast.verdict is Verdict.CONFIRMED
    assert late.verdict is Verdict.NOT_CHECKED
    assert late.verdict_label == "nie sprawdzono"
    assert late.limitations == [pipeline.TIME_LIMIT.format(budget=1.0)]
    # The late claim was cut during the free search: no model request to price.
    assert result.cost_usd == pytest.approx(OPUS + 2 * (HAIKU + SONNET))


def check(claim, queries, budget_s, exclude_url=None):
    async def run():
        deadline = asyncio.get_running_loop().time() + budget_s
        return await pipeline.check_claim(claim, queries, deadline, exclude_url)

    return asyncio.run(run())


def test_one_retry_with_the_claim_as_query_when_time_remains(monkeypatch, models):
    claim = "Polska wstąpiła do UE w 2004 roku."
    seen = fake_search(monkeypatch, found=lambda q: q == claim)
    result = check(claim, ["model 1", "model 2"], budget_s=30)
    assert seen == ["model 1", "model 2", claim]
    assert result.judgement.verdict is Verdict.CONFIRMED
    assert "retry_web" in result.steps_ms and "retry_judge" in result.steps_ms
    # The web found pages on the retry: its first failure is no longer a limitation.
    assert websearch.SEARCH_UNAVAILABLE not in result.judgement.limitations


def test_no_retry_without_time_left(monkeypatch, models):
    claim = "Polska wstąpiła do UE w 2004 roku."
    seen = fake_search(monkeypatch, found=lambda q: q == claim)
    result = check(claim, ["model 1"], budget_s=pipeline.RETRY_MIN_S - 1)
    assert seen == ["model 1"]
    assert "retry_web" not in result.steps_ms
    # Fact Check without a key and web empty: no verdict.
    assert result.judgement.verdict is Verdict.NOT_CHECKED
    assert result.judgement.limitations == [
        pipeline.SOURCES_FAILED,
        pipeline.factcheck.LOOKUP_UNAVAILABLE,
        pipeline.euvsdisinfo.LOOKUP_UNAVAILABLE,
        websearch.SEARCH_UNAVAILABLE,
    ]


def test_linked_page_is_not_evidence_for_its_own_claims(monkeypatch, models):
    fake_search(monkeypatch)
    page = "https://gov.pl/model-1"
    result = check("Twierdzenie.", ["model 1", "model 2"], 5, exclude_url=page)
    urls = {str(s.url) for s in result.judgement.sources}
    assert urls == {"https://www.gov.pl/model-2"}


def test_judge_failure_is_a_limitation_without_retry(monkeypatch):
    seen = fake_search(monkeypatch)

    def failing(messages, info):
        raise ModelHTTPError(529, "claude", "overloaded")

    with (
        rerank.agent.override(model=model(every_fragment)),
        judge.agent.override(model=FunctionModel(failing)),
    ):
        result = check("Twierdzenie.", ["model 1"], 30)
    assert result.judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert judge.JUDGE_UNAVAILABLE in result.judgement.limitations
    assert seen == ["model 1"]
    assert result.cost_usd is None


def test_a_crashing_source_is_a_limitation_of_that_source(monkeypatch, models):
    async def crash(query, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(websearch, "search_web", crash)
    result = check("Twierdzenie.", ["model 1"], 30)
    assert result.judgement.verdict is Verdict.NOT_CHECKED
    assert websearch.SEARCH_UNAVAILABLE in result.judgement.limitations


@pytest.mark.parametrize("queries", [[], ["Twierdzenie."]])
def test_no_retry_that_would_repeat_the_first_search(monkeypatch, models, queries):
    seen = fake_search(monkeypatch, found=lambda q: False)
    result = check("Twierdzenie.", queries, 30)
    assert seen == ["Twierdzenie."]
    assert "retry_web" not in result.steps_ms


def test_retry_cut_by_the_deadline_keeps_the_first_pass(monkeypatch):
    claim = "Polska wstąpiła do UE w 2004 roku."
    fake_search(monkeypatch, found=lambda q: q == claim)
    monkeypatch.setattr(pipeline, "RETRY_MIN_S", 0.1)

    async def slow_rank(messages, info):
        await asyncio.sleep(60)

    with rerank.agent.override(model=FunctionModel(slow_rank)):
        result = check(claim, ["model 1"], budget_s=0.5)
    assert result.judgement.verdict is Verdict.NOT_CHECKED
    # The retry found pages: time ran out, not the sources.
    assert result.judgement.limitations[0] == pipeline.TIME_LIMIT.format(
        budget=pipeline.CHECK_BUDGET_S
    )
    assert websearch.SEARCH_UNAVAILABLE in result.judgement.limitations
    assert result.cost_usd is None


def test_injection_in_a_source_reaches_the_check_result(monkeypatch):
    fake_search(monkeypatch)

    def flagged(prompt):
        labels = judge.Labels.model_validate_json(supports_all(prompt))
        return labels.model_copy(update={"injection_found": True}).model_dump_json()

    with (
        rerank.agent.override(model=model(every_fragment)),
        judge.agent.override(model=model(flagged, "claude-sonnet-5-5")),
    ):
        result = verify("tekst", claims(2))
    assert [e.location for e in result.security_events] == ["source"]
    assert all(c.verdict is Verdict.CONFIRMED for c in result.claims)


def test_euvsdisinfo_match_alone_gives_no_verdict(monkeypatch, models):
    """A known-narrative match is context: one EUvsDisinfo case never decides the verdict."""
    case = pipeline.euvsdisinfo.EuvsdisinfoHit(
        kind="claim_review",
        source=document("https://euvsdisinfo.eu/report/x")
        .to_source(fragment=f"Wstęp. {QUOTE}")
        .model_copy(
            update={"source_type": "disinfo_database", "publisher": "EUvsDisinfo"}
        ),
    )

    async def search_cases(claim, **kwargs):
        return pipeline.euvsdisinfo.EuvsdisinfoLookup(hits=[case])

    monkeypatch.setattr(pipeline.euvsdisinfo, "search_cases", search_cases)
    fake_search(monkeypatch, found=lambda q: False)
    result = check("Twierdzenie.", ["model 1"], 5)
    assert result.judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert [str(s.url) for s in result.judgement.sources] == [
        "https://euvsdisinfo.eu/report/x"
    ]
