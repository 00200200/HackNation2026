"""Check log (#14): every check through the API leaves one complete record, read back and deleted
per session. Offline: a fake extraction model, every source fails fast."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

import prawdowid.app as app_module
from prawdowid.app import app, limiter
from prawdowid.contract import ClaimKind
from prawdowid.verifier import ExtractedClaim, Extraction, agent

PESEL = "44051401359"
TEXT = f"Jan Kowalski, PESEL {PESEL}, twierdzi, że PKB Polski wzrósł o 3%."
FIELDS = {
    "session",
    "time",
    "started_at",
    "latency_ms",
    "channel",
    "question",
    "status",
    "error",
    "message",
    "page",
    "steps_ms",
    "model_calls",
    "cost_usd",
    "unpriced_requests",
    "security_events",
    "incidents",
    "limitations",
    "claims",
    "unchecked_claims",
}


def extraction(messages, info):
    out = Extraction(
        claims=[
            ExtractedClaim(
                claim="PKB Polski wzrósł o 3%.",
                kind=ClaimKind.STATEMENT,
                source_sentence="PKB Polski wzrósł o 3%.",
                checkable=True,
                reason="Dane GUS.",
                queries=["PKB Polski"],
            )
        ],
        other_claims=[],
        unclear=False,
        injection_found=True,
    )
    return ModelResponse(parts=[TextPart(out.model_dump_json())])


@pytest.fixture
def api():
    limiter.reset()
    with agent.override(model=FunctionModel(extraction, model_name="fake-extract")):
        yield TestClient(app)


def check(api, session="session-0001", channel="web"):
    headers = {"X-Session-Id": session, "X-Channel": channel}
    resp = api.post("/api/checks", json={"input": TEXT}, headers=headers)
    assert resp.status_code == 200
    [rec] = api.get(f"/api/sessions/{session}").json()
    assert set(rec) == FIELDS
    assert PESEL not in str(rec)
    return resp.json(), rec


@pytest.mark.usefixtures("quiet_sources")
def test_a_successful_check_leaves_one_complete_record(api):
    body, rec = check(api, channel="discord")
    assert rec["channel"] == "discord" and rec["status"] == "ok"
    assert rec["error"] is None and rec["latency_ms"] >= 0
    assert rec["started_at"] <= rec["time"]
    assert set(rec["steps_ms"]) == {"extract"}
    assert rec["model_calls"][0]["model"] == "fake-extract"
    assert rec["security_events"] == [
        {"kind": "prompt_injection", "location": "input", "detector": "model"}
    ]
    [claim] = rec["claims"]
    # Every source answers with nothing: an abstention with its reason is in the record.
    assert claim["verdict"] == "insufficient_evidence" and claim["limitations"]
    assert {"factcheck", "web"} <= set(claim["steps_ms"])
    # The log-only fields never reach a channel.
    assert "steps_ms" not in body and "model_calls" not in body
    assert "steps_ms" not in body["claims"][0]


@pytest.mark.parametrize(
    ("sent", "logged"),
    [
        ({}, "web"),
        ({"X-Channel": "discord"}, "discord"),
        ({"x-channel": "discord"}, "discord"),
        ({"X-Channel": "demo"}, "demo"),
        ({"X-Channel": "slack"}, "other"),
    ],
)
def test_channel_header_has_a_default_and_a_fallback(api, sent, logged):
    # The session header is lowercase here: header names are case-insensitive.
    headers = {"x-session-id": "channel-0001", **sent}
    api.post("/api/checks", json={"input": TEXT}, headers=headers)
    [rec] = api.get("/api/sessions/channel-0001").json()
    assert rec["channel"] == logged


def test_a_failed_check_leaves_one_record(api, monkeypatch):
    async def broken(text):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "verify", broken)
    body, rec = check(api)
    assert body["status"] == rec["status"] == "technical_error"
    assert rec["error"] == "RuntimeError" and rec["claims"] == []
    assert rec["limitations"] == body["limitations"] != []


def test_a_timed_out_check_leaves_one_record(api, monkeypatch):
    async def slow(text):
        await asyncio.sleep(5)

    monkeypatch.setattr(app_module, "verify", slow)
    monkeypatch.setattr(app_module, "VERIFY_TIMEOUT_S", 0.05)
    body, rec = check(api)
    assert body["status"] == rec["status"] == "technical_error"
    assert rec["error"] == "timeout"


def test_records_are_read_back_and_deleted_per_session(api):
    check(api, "session-0001")
    api.post("/api/checks", json={"input": TEXT}, headers={"X-Session-Id": "other-01"})
    api.post("/api/checks", json={"input": TEXT}, headers={"X-Session-Id": "other-01"})
    assert len(api.get("/api/sessions/other-01").json()) == 2
    assert api.delete("/api/sessions/session-0001").json() == {"deleted": 1}
    assert api.get("/api/sessions/session-0001").json() == []
    assert len(api.get("/api/sessions/other-01").json()) == 2
    assert api.get("/api/sessions/bad").status_code == 422


def test_a_link_check_records_the_masked_page_and_fetch_time(api, monkeypatch):
    from prawdowid import link

    async def fetch(url):
        return link.Page(
            url="https://news.example/a?mail=jan.kowalski@example.com",
            sha256="0" * 64,
            title=None,
            publisher=None,
            published_at=None,
            text="PKB Polski wzrósł o 3%.",
        )

    # A refused link (private address) leaves a record with its fetch time.
    url = {"input": "http://10.0.0.1/"}
    api.post("/api/checks", json=url, headers={"X-Session-Id": "link-0001"})
    monkeypatch.setattr("prawdowid.verifier.fetch_page", fetch)
    url = {"input": "https://news.example/a?mail=jan.kowalski@example.com"}
    api.post("/api/checks", json=url, headers={"X-Session-Id": "link-0001"})
    refused, page = api.get("/api/sessions/link-0001").json()
    assert "jan.kowalski" not in str(page) + str(refused)
    assert page["page"]["sha256"] == "0" * 64
    assert set(page["steps_ms"]) == {"fetch", "extract"}
    assert refused["status"] == "cannot_check" and set(refused["steps_ms"]) == {"fetch"}


def test_a_failed_model_call_is_in_the_record():
    def garbage(messages, info):
        return ModelResponse(parts=[TextPart("not json")])

    limiter.reset()
    with agent.override(model=FunctionModel(garbage, model_name="fake-extract")):
        _, rec = check(TestClient(app))
    assert rec["status"] == "technical_error" and rec["error"] is None
    assert set(rec["steps_ms"]) == {"extract"} and rec["cost_usd"] == 0.0
    assert rec["unpriced_requests"] == 1
    # The answer that failed validation was billed: it is in the record.
    assert [m["model"] for m in rec["model_calls"]] == ["fake-extract"]


def test_expired_records_are_not_read_back(api, check_log):
    import json
    from datetime import UTC, datetime, timedelta

    from prawdowid.privacy import RETENTION_DAYS

    old = datetime.now(UTC) - timedelta(days=RETENTION_DAYS, seconds=1)
    check_log.write_text(json.dumps({"session": "old-0001", "time": old.isoformat()}))
    assert api.get("/api/sessions/old-0001").json() == []
