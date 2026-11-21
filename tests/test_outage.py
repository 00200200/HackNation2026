"""#60 and #63: an outage is never a verdict, scenario D stays an abstention, the eval fault
switch is closed to the public, and the budget defaults that let a long page be judged."""

import asyncio
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from prawdowid import app as app_module
from prawdowid import discord_bot, faults, judge, pipeline, rerank, verifier, websearch
from prawdowid.contract import ClaimKind, ClaimResult, Status, Verdict
from tests.test_pipeline import (
    every_fragment,
    fake_search,
    model,
    supports_all,
)

CLAIM = "Polska wstąpiła do UE w 2004 roku."


@pytest.fixture
def models():
    with (
        rerank.agent.override(model=model(every_fragment)),
        judge.agent.override(model=model(supports_all, "claude-sonnet-5-5")),
    ):
        yield


def fact_check(monkeypatch, *, down: bool):
    """Fact Check either fails (key, quota, timeout) or answers with no hits."""

    async def search_claims(claim, **kwargs):
        return pipeline.factcheck.FactCheckLookup(
            limitation=pipeline.factcheck.LOOKUP_UNAVAILABLE if down else None
        )

    monkeypatch.setattr(pipeline.factcheck, "search_claims", search_claims)


def web(monkeypatch, answer):
    """`answer(query)` is the WebSearch each web query gets."""

    async def search(query, **kwargs):
        return answer(query)

    monkeypatch.setattr(websearch, "search_web", search)


def check(queries=("a", "b")):
    async def run():
        deadline = asyncio.get_running_loop().time() + 30
        return await pipeline.check_claim(CLAIM, list(queries), deadline)

    return asyncio.run(run())


FAILED = websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE, failed=True)


# --- #60: failed is not found nothing ---------------------------------------------------------


def test_fact_check_down_and_nothing_found_is_an_outage_not_an_abstention(monkeypatch):
    fact_check(monkeypatch, down=True)
    web(monkeypatch, lambda q: websearch.WebSearch())  # the search answered, no hits
    result = check()
    assert result.judgement.verdict is Verdict.NOT_CHECKED
    assert result.outage
    reason = result.judgement.limitations[0]
    assert "Nie mogę teraz sprawdzić bazy Google Fact Check" in reason
    assert Verdict.INSUFFICIENT_EVIDENCE.label not in " ".join(
        result.judgement.limitations
    )


def test_every_web_query_failing_is_an_outage(monkeypatch):
    fact_check(monkeypatch, down=False)
    web(monkeypatch, lambda q: FAILED)
    result = check()
    assert result.judgement.verdict is Verdict.NOT_CHECKED and result.outage
    assert "wyszukiwarki internetowej" in result.judgement.limitations[0]


def test_scenario_d_nothing_found_everywhere_stays_an_abstention(monkeypatch):
    """Every source answered and none had evidence: that is "brak wystarczających dowodów"."""
    fact_check(monkeypatch, down=False)
    web(monkeypatch, lambda q: websearch.WebSearch())
    result = check()
    assert result.judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert not result.outage


def test_one_failed_query_among_empty_ones_is_still_an_abstention(monkeypatch):
    fact_check(monkeypatch, down=False)
    web(monkeypatch, lambda q: FAILED if q == "a" else websearch.WebSearch())
    result = check()
    assert result.judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert not result.outage


def test_pages_that_could_not_be_read_are_not_an_outage(monkeypatch):
    fact_check(monkeypatch, down=False)
    web(
        monkeypatch, lambda q: websearch.WebSearch(limitation=websearch.NOTHING_FETCHED)
    )
    result = check()
    assert result.judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert not result.outage


def test_found_evidence_stands_when_fact_check_is_down(monkeypatch, models):
    fact_check(monkeypatch, down=True)
    fake_search(monkeypatch)
    result = check()
    assert result.judgement.verdict is Verdict.CONFIRMED
    assert not result.outage
    assert pipeline.factcheck.LOOKUP_UNAVAILABLE in result.judgement.limitations


def test_gov_pl_down_blocks_an_abstention_only_for_a_government_claim(monkeypatch):
    monkeypatch.setattr(pipeline.govpl, "ENABLED", True)
    fact_check(monkeypatch, down=False)
    web(monkeypatch, lambda q: websearch.WebSearch())

    async def search_govpl(queries):
        return websearch.WebSearch(limitation=pipeline.govpl.LOOKUP_UNAVAILABLE)

    monkeypatch.setattr(pipeline.govpl, "search_govpl", search_govpl)

    async def run(govpl_queries):
        deadline = asyncio.get_running_loop().time() + 30
        return await pipeline.check_claim(
            CLAIM, ["a"], deadline, govpl_queries=govpl_queries
        )

    government = asyncio.run(run(["RCB alert"]))
    assert government.outage and "www.gov.pl" in government.judgement.limitations[0]
    other = asyncio.run(run([]))
    assert other.judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE and not other.outage


def test_web_search_answers_nothing_is_no_limitation(monkeypatch):
    async def go():
        return await websearch.search_web(
            "x", provider=lambda q, *, domains, limit: [], save=False
        )

    result = asyncio.run(go())
    assert result.limitation is None and not result.failed


def test_a_provider_failure_is_marked_failed():
    def failing(query, *, domains, limit):
        raise websearch.SearchUnavailable("quota")

    async def go():
        return await websearch.search_web("x", provider=failing, save=False)

    result = asyncio.run(go())
    assert result.failed and result.limitation == websearch.SEARCH_UNAVAILABLE


# --- #60: the technical error reaches the answer -------------------------------------------------


def extraction(n=2):
    return verifier.Extraction(
        claims=[
            verifier.ExtractedClaim(
                claim=f"Twierdzenie {i}.",
                kind=ClaimKind.STATEMENT,
                source_sentence=f"Twierdzenie {i}.",
                checkable=True,
                reason="Fakt.",
                queries=[f"q{i}"],
            )
            for i in range(n)
        ],
        other_claims=[],
        unclear=False,
    )


def verify(text="tekst", n=2):
    with verifier.agent.override(
        model=model(lambda _: extraction(n).model_dump_json(), "claude-opus-5-5")
    ):
        return asyncio.run(verifier.verify(text))


def test_every_claim_hitting_an_outage_is_a_technical_error(monkeypatch):
    fact_check(monkeypatch, down=True)
    web(monkeypatch, lambda q: websearch.WebSearch())
    result = verify()
    assert result.status is Status.TECHNICAL_ERROR
    assert result.claims == [] and result.unchecked_claims == []
    assert "Nie mogę teraz sprawdzić bazy Google Fact Check" in result.message
    assert result.cost_usd is not None  # the extraction call is still priced


def test_a_claim_without_outage_keeps_the_answer_ok(monkeypatch):
    """Only claims that hit an outage are blamed on it; one real abstention keeps status ok."""
    fact_check(monkeypatch, down=False)
    web(monkeypatch, lambda q: websearch.WebSearch())
    result = verify()
    assert result.status is Status.OK
    assert {c.verdict for c in result.claims} == {Verdict.INSUFFICIENT_EVIDENCE}


# --- #60: the eval-only fault switch -------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "headers", "expected"),
    [
        (None, {"x-eval-fault": "llm_unavailable", "x-eval-token": "s"}, None),
        ("s", {"x-eval-fault": "llm_unavailable"}, None),
        ("s", {"x-eval-fault": "llm_unavailable", "x-eval-token": "wrong"}, None),
        ("s", {"x-eval-fault": "unknown", "x-eval-token": "s"}, None),
        ("s", {"x-eval-token": "s"}, None),
        (
            "s",
            {"x-eval-fault": "llm_unavailable", "x-eval-token": "s"},
            "llm_unavailable",
        ),
        (
            "s",
            {"x-eval-fault": "factcheck_api_unavailable", "x-eval-token": "s"},
            "factcheck_api_unavailable",
        ),
    ],
)
def test_fault_needs_the_server_side_eval_token(monkeypatch, env, headers, expected):
    if env is None:
        monkeypatch.delenv(faults.TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(faults.TOKEN_ENV, env)
    assert faults.requested(headers) == expected


def test_simulated_fact_check_outage_skips_the_real_lookup(monkeypatch):
    async def real(claim, **kwargs):
        raise AssertionError("the real lookup must not run")

    monkeypatch.setattr(pipeline.factcheck, "search_claims", real)
    web(monkeypatch, lambda q: websearch.WebSearch())
    with faults.simulate(faults.FACTCHECK_UNAVAILABLE):
        result = check()
    assert result.outage
    assert "bazy Google Fact Check" in result.judgement.limitations[0]


def api_check(headers):
    app_module.limiter.reset()
    client = TestClient(app_module.app)
    with verifier.agent.override(
        model=model(lambda _: extraction(1).model_dump_json(), "claude-opus-5-5")
    ):
        return client.post(
            "/api/checks", json={"input": "Twierdzenie."}, headers=headers
        ).json()


def test_public_user_cannot_switch_the_model_off(monkeypatch):
    fact_check(monkeypatch, down=False)
    web(monkeypatch, lambda q: websearch.WebSearch())
    monkeypatch.setenv(faults.TOKEN_ENV, "secret")
    for headers in (
        {"X-Eval-Fault": "llm_unavailable"},
        {"X-Eval-Fault": "llm_unavailable", "X-Eval-Token": "guess"},
    ):
        assert api_check(headers)["status"] == "ok"


def test_eval_traffic_with_the_token_simulates_the_model_outage(monkeypatch):
    monkeypatch.setenv(faults.TOKEN_ENV, "secret")
    body = api_check({"X-Eval-Fault": "llm_unavailable", "X-Eval-Token": "secret"})
    assert body["status"] == "technical_error"
    assert body["message"] == verifier.MODEL_FAILED and body["claims"] == []


def test_the_switch_ends_with_its_block():
    async def go():
        with faults.simulate(faults.LLM_UNAVAILABLE):
            inside = faults.active(faults.LLM_UNAVAILABLE)
        return inside, faults.active(faults.LLM_UNAVAILABLE)

    assert asyncio.run(go()) == (True, False)


def test_eval_traffic_with_the_token_simulates_the_fact_check_outage(monkeypatch):
    monkeypatch.setenv(faults.TOKEN_ENV, "secret")
    web(monkeypatch, lambda q: websearch.WebSearch())
    body = api_check(
        {"X-Eval-Fault": "factcheck_api_unavailable", "X-Eval-Token": "secret"}
    )
    assert body["status"] == "technical_error"
    assert "Nie mogę teraz sprawdzić bazy Google Fact Check" in body["message"]


def test_adapter_sends_the_fault_headers_only_for_a_simulating_case(monkeypatch):
    from evals import adapter

    monkeypatch.setenv(faults.TOKEN_ENV, "secret")
    assert adapter.fault_headers({"text": "x"}) == {}
    assert adapter.fault_headers({"text": "x", "simulate": "llm_unavailable"}) == {
        "X-Eval-Fault": "llm_unavailable",
        "X-Eval-Token": "secret",
    }
    monkeypatch.delenv(faults.TOKEN_ENV)
    with pytest.raises(RuntimeError, match=faults.TOKEN_ENV):
        adapter.fault_headers({"simulate": "llm_unavailable"})


def test_run_passes_the_case_fault_to_the_adapter(monkeypatch):
    from evals import adapter, run

    asked = []
    monkeypatch.setattr(adapter, "wait_turn", lambda: None)
    monkeypatch.setattr(
        adapter, "ask", lambda payload, channel: asked.append(payload) or {}
    )
    run.call({"input": {"text": "x"}, "simulate": "llm_unavailable"}, "web")
    run.call({"input": {"text": "y"}}, "web")
    assert asked == [{"text": "x", "simulate": "llm_unavailable"}, {"text": "y"}]


# --- #60: Discord does not print "nie sprawdzono" as a grade --------------------------------------


def test_discord_does_not_grade_a_claim_that_was_not_checked():
    claim = ClaimResult(
        claim="Fakt.",
        kind=ClaimKind.STATEMENT,
        source_sentence="Fakt.",
        verdict=Verdict.NOT_CHECKED,
        reasoning="",
        strength="brak",
        premises=[],
        sources=[],
        limitations=["Skończył się czas."],
    )
    text = discord_bot._claim(1, claim, None)
    assert "Bez oceny: **nie sprawdzono**" in text and "Ocena:" not in text


# --- #63: defaults that let a long page be judged -------------------------------------------------


def defaults(**env):
    """CHECK_BUDGET_S and MAX_CHECKED_CLAIMS as a fresh process reads them."""
    clean = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PRAWDOWID_CHECK_BUDGET_S", "PRAWDOWID_MAX_CHECKED_CLAIMS")
    }
    code = (
        "from prawdowid import pipeline, verifier;"
        "print(pipeline.CHECK_BUDGET_S, verifier.MAX_CHECKED_CLAIMS)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={**clean, **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    budget, claims = out.split()
    return float(budget), int(claims)


def test_budget_and_claim_cap_defaults():
    budget, claims = defaults()
    assert (budget, claims) == (40, 3)
    # Inside the API's own limit, so a check ends with an answer, not a 60 s cut.
    assert budget < app_module.VERIFY_TIMEOUT_S


def test_budget_and_claim_cap_can_be_set_by_env():
    env = {"PRAWDOWID_CHECK_BUDGET_S": "45", "PRAWDOWID_MAX_CHECKED_CLAIMS": "2"}
    assert defaults(**env) == (45, 2)
