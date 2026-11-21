import asyncio

import pytest
from fastapi.testclient import TestClient

from prawdowid import app as app_module
from prawdowid import checklog
from prawdowid.app import MAX_INPUT_CHARS, RATE_LIMIT_MESSAGE, app, limiter


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAWDOWID_DB_PATH", str(tmp_path / "checks.sqlite3"))
    limiter.reset()
    with TestClient(app) as c:
        yield c


def test_valid_input_is_stored_and_returned(client):
    resp = client.post(
        "/api/checks", json={"input": "  Ziemia jest płaska.  ", "session_id": "s1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["status"] == "cannot_check"
    assert body["result"]["claims"] == []
    assert body["result"]["message"]

    stored = client.get(f"/api/checks/{body['id']}").json()
    assert stored["input"] == "Ziemia jest płaska."
    assert stored["session_id"] == "s1"
    assert stored["channel"] == "api"
    assert stored["result"] == body["result"]
    assert [c["id"] for c in client.get("/api/checks").json()] == [body["id"]]


def test_web_page_shows_not_connected_notice(client):
    resp = client.post("/", data={"input": "https://example.com/artykul"})
    assert resp.status_code == 200
    assert 'class="notice"' in resp.text
    assert "nie możemy teraz ocenić tej treści" in resp.text
    assert 'class="verdict"' not in resp.text
    row = checklog.list_all()[0]
    assert row["channel"] == "web"
    assert row["session_id"] == resp.cookies["prawdowid_session"]


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
def test_invalid_input_is_rejected(client, text):
    assert client.post("/api/checks", json={"input": text}).status_code == 422
    assert client.post("/", data={"input": text}).status_code == 422
    assert checklog.list_all() == []


def test_verify_exception_yields_technical_error_and_is_logged(
    client, monkeypatch, caplog
):
    async def broken(text):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "verify", broken)
    resp = client.post("/api/checks", json={"input": "Coś do sprawdzenia"})
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "technical_error"
    assert "boom" not in resp.text
    assert "verify failed" in caplog.text
    assert checklog.list_all()[0]["status"] == "technical_error"


def test_session_deletion_removes_rows(client):
    for session in ["a", "a", "b"]:
        client.post("/api/checks", json={"input": "Tekst", "session_id": session})
    assert client.delete("/api/sessions/a").json() == {"deleted": 2}
    assert [c["session_id"] for c in client.get("/api/checks").json()] == ["b"]


def test_unknown_check_is_404(client):
    assert client.get("/api/checks/missing").status_code == 404


def test_web_form_is_rate_limited(client):
    for _ in range(10):
        assert client.post("/", data={"input": "Tekst"}).status_code == 200
    resp = client.post("/", data={"input": "Tekst"})
    assert resp.status_code == 429
    assert RATE_LIMIT_MESSAGE in resp.text


def test_verify_timeout_yields_technical_error(client, monkeypatch):
    async def slow(text):
        await asyncio.sleep(1)

    monkeypatch.setattr(app_module, "verify", slow)
    monkeypatch.setattr(app_module, "VERIFY_TIMEOUT_S", 0.01)
    resp = client.post("/api/checks", json={"input": "Tekst"})
    assert resp.json()["result"]["status"] == "technical_error"
    assert checklog.list_all()[0]["status"] == "technical_error"
