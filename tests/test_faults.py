import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prawdowid import factcheck, faults
from prawdowid.app import app, limiter
from prawdowid.verifier import MODEL_FAILED, agent
from tests.test_app import MIXED


@pytest.fixture
def client():
    limiter.reset()
    model = FunctionModel(
        lambda messages, info: ModelResponse(parts=[TextPart(MIXED.model_dump_json())])
    )
    with agent.override(model=model):
        yield TestClient(app)


def check(client, fault: str) -> dict:
    resp = client.post(
        "/api/checks", json={"input": "Fakt i opinia."}, headers={faults.HEADER: fault}
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("fault", sorted(faults.MODEL_ERRORS))
def test_switch_is_off_by_default(client, monkeypatch, fault):
    monkeypatch.delenv(faults.ENV, raising=False)
    assert check(client, fault)["status"] == "ok"


@pytest.mark.parametrize("fault", sorted(faults.MODEL_ERRORS))
def test_model_fault_is_a_technical_error_without_verdicts(client, monkeypatch, fault):
    monkeypatch.setenv(faults.ENV, "1")
    body = check(client, fault)
    assert body["status"] == "technical_error"
    assert body["message"] == MODEL_FAILED
    assert body["claims"] == []


def test_unknown_fault_is_ignored(client, monkeypatch):
    monkeypatch.setenv(faults.ENV, "1")
    assert check(client, "everything_down")["status"] == "ok"


def test_factcheck_fault_takes_the_outage_path(client, monkeypatch, caplog):
    monkeypatch.setenv(faults.ENV, "1")
    # Without the fault, a set key would send a request to Google.
    monkeypatch.setenv(factcheck.KEY_ENV, "set")
    with caplog.at_level(logging.WARNING, logger="prawdowid"):
        body = check(client, faults.FACTCHECK_DOWN)
    # A source outage is a limitation of the claim, not a failed check.
    assert body["status"] == "ok"
    assert factcheck.LOOKUP_UNAVAILABLE in body["claims"][0]["limitations"]
    assert "factcheck unavailable: eval fault" in caplog.text


def test_factcheck_lookup_under_the_fault_sends_no_request(monkeypatch):
    monkeypatch.setenv(factcheck.KEY_ENV, "set")
    token = faults.active.set(faults.FACTCHECK_DOWN)
    try:
        lookup = asyncio.run(factcheck.search_claims("Sejm liczy 460 posłów."))
    finally:
        faults.active.reset(token)
    assert lookup.limitation == factcheck.LOOKUP_UNAVAILABLE
    assert lookup.hits == []
