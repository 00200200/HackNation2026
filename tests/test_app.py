import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from prawdowid import app as app_module
from prawdowid.app import MAX_INPUT_CHARS, RATE_LIMIT_MESSAGE, app, limiter
from prawdowid.contract import CheckResult, ClaimResult, Source, Status, Verdict


@pytest.fixture
def client():
    limiter.reset()
    return TestClient(app)


def test_http_link_is_accepted(client):
    resp = client.post("/api/checks", json={"input": "https://example.com/artykul"})
    assert resp.status_code == 200


def test_valid_input_returns_not_connected_notice(client):
    resp = client.post("/api/checks", json={"input": "  Ziemia jest płaska.  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cannot_check"
    assert body["claims"] == []
    assert "nie jest jeszcze podłączona" in body["message"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n ",
        "x" * (MAX_INPUT_CHARS + 1),
        "ftp://example.com/a",
        "javascript://alert(1)",
    ],
)
def test_invalid_input_is_rejected_with_polish_message(client, text):
    resp = client.post("/api/checks", json={"input": text})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["type"] in {"empty", "too_long", "bad_url"}


def test_verify_exception_yields_technical_error_and_is_logged(
    client, monkeypatch, caplog
):
    async def broken(text):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "verify", broken)
    resp = client.post("/api/checks", json={"input": "Coś do sprawdzenia"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "technical_error"
    assert "boom" not in resp.text
    assert "verify failed" in caplog.text


def test_verify_timeout_yields_technical_error(client, monkeypatch):
    async def slow(text):
        await asyncio.sleep(1)

    monkeypatch.setattr(app_module, "verify", slow)
    monkeypatch.setattr(app_module, "VERIFY_TIMEOUT_S", 0.01)
    resp = client.post("/api/checks", json={"input": "Tekst"})
    assert resp.json()["status"] == "technical_error"


def test_rate_limit(client):
    for _ in range(10):
        assert client.post("/api/checks", json={"input": "Tekst"}).status_code == 200
    resp = client.post("/api/checks", json={"input": "Tekst"})
    assert resp.status_code == 429
    assert resp.json() == {"detail": RATE_LIMIT_MESSAGE}


def test_claim_serializes_polish_verdict_label():
    claim = ClaimResult(
        claim="c",
        verdict=Verdict.MISLEADING,
        reasoning="r",
        strength="s",
        premises=[],
        sources=[
            Source(
                title="t",
                publisher="p",
                published_at=None,
                fetched_at=datetime.now(UTC),
                url="https://example.com",
                source_type="article",
            )
        ],
        limitations=[],
    )
    data = CheckResult(status=Status.OK, claims=[claim]).model_dump(mode="json")
    assert data["claims"][0]["verdict_label"] == "wprowadzające w błąd"


def test_non_ok_status_needs_a_message():
    with pytest.raises(ValueError):
        CheckResult(status=Status.CANNOT_CHECK)
