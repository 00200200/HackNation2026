import pytest
from fastapi.testclient import TestClient

from prawdowid import app as app_module
from prawdowid import moderation
from prawdowid.app import app, limiter
from prawdowid.contract import CheckResult, ClaimKind, ClaimResult, Status, Verdict

QUESTION = "Czy od 1 stycznia parkowanie przy szpitalu będzie kosztować 10 zł?"


def result(verdict: Verdict) -> CheckResult:
    claim = ClaimResult(
        claim="c",
        kind=ClaimKind.STATEMENT,
        source_sentence="c",
        verdict=verdict,
        reasoning="r",
        strength="brak",
        premises=[],
        sources=[],
        limitations=[],
    )
    return CheckResult(status=Status.OK, claims=[claim])


@pytest.fixture
def client(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(app_module, "MODERATOR_TOKEN", "sekret")
    return TestClient(app)


def answering(monkeypatch, verdict: Verdict) -> None:
    async def verify(text):
        return result(verdict)

    monkeypatch.setattr(app_module, "verify", verify)


def test_same_question_twice_is_one_case(client, monkeypatch):
    answering(monkeypatch, Verdict.INSUFFICIENT_EVIDENCE)
    first = client.post("/api/checks", json={"input": QUESTION}).json()
    again = client.post("/api/checks", json={"input": "  " + QUESTION.upper()}).json()
    assert first["moderator_case_id"]
    assert again["moderator_case_id"] == first["moderator_case_id"]
    assert moderation.get(first["moderator_case_id"]).asked == 2


def test_a_verdict_opens_no_case(client, monkeypatch):
    answering(monkeypatch, Verdict.CONFIRMED)
    body = client.post("/api/checks", json={"input": QUESTION}).json()
    assert body["moderator_case_id"] is None
    assert moderation.list_cases() == []


def test_moderator_answer_is_shown_next_to_the_result(client, monkeypatch):
    answering(monkeypatch, Verdict.INSUFFICIENT_EVIDENCE)
    case = client.post("/api/checks", json={"input": QUESTION}).json()[
        "moderator_case_id"
    ]
    auth = {"Authorization": "Bearer sekret"}
    listed = client.get("/api/moderator/cases", headers=auth).json()
    assert [c["id"] for c in listed] == [case]
    resp = client.post(
        f"/api/moderator/cases/{case}/answer", json={"answer": " Nie. "}, headers=auth
    )
    assert resp.json()["answer"] == "Nie."
    body = client.post("/api/checks", json={"input": QUESTION}).json()
    assert body["moderator_answer"]["text"] == "Nie."
    assert body["claims"][0]["verdict"] == "insufficient_evidence"


@pytest.mark.parametrize(
    ("token", "headers", "status"),
    [
        ("", {"Authorization": "Bearer sekret"}, 404),
        ("sekret", {}, 401),
        ("sekret", {"Authorization": "Bearer zle"}, 401),
    ],
)
def test_panel_needs_the_token(client, monkeypatch, token, headers, status):
    monkeypatch.setattr(app_module, "MODERATOR_TOKEN", token)
    assert client.get("/api/moderator/cases", headers=headers).status_code == status


def test_answer_to_a_missing_case_is_404(client):
    resp = client.post(
        "/api/moderator/cases/ABCDEF1234567890/answer",
        json={"answer": "x"},
        headers={"Authorization": "Bearer sekret"},
    )
    assert resp.status_code == 404


def test_case_stores_the_masked_question():
    case = moderation.open_case("Czy jan.kowalski@example.com dostanie mandat?")
    assert "example.com" not in case.question


def test_empty_answer_is_refused_in_polish(client, monkeypatch):
    answering(monkeypatch, Verdict.INSUFFICIENT_EVIDENCE)
    case = client.post("/api/checks", json={"input": QUESTION}).json()[
        "moderator_case_id"
    ]
    resp = client.post(
        f"/api/moderator/cases/{case}/answer",
        json={"answer": "   "},
        headers={"Authorization": "Bearer sekret"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["msg"] == "Wpisz odpowiedź."


def test_no_case_while_the_panel_is_off(client, monkeypatch):
    monkeypatch.setattr(app_module, "MODERATOR_TOKEN", "")
    answering(monkeypatch, Verdict.INSUFFICIENT_EVIDENCE)
    body = client.post("/api/checks", json={"input": QUESTION}).json()
    assert body["moderator_case_id"] is None
    assert moderation.list_cases() == []


def test_auth_comes_before_the_answer_is_validated(client):
    resp = client.post(
        "/api/moderator/cases/ABCDEF1234567890/answer", json={"answer": "  "}
    )
    assert resp.status_code == 401


def test_too_long_answer_is_refused_in_polish(client, monkeypatch):
    answering(monkeypatch, Verdict.INSUFFICIENT_EVIDENCE)
    case = client.post("/api/checks", json={"input": QUESTION}).json()[
        "moderator_case_id"
    ]
    resp = client.post(
        f"/api/moderator/cases/{case}/answer",
        json={"answer": "x" * (moderation.MAX_ANSWER_CHARS + 1)},
        headers={"Authorization": "Bearer sekret"},
    )
    assert resp.status_code == 422
    assert "za długa" in resp.json()["detail"][0]["msg"]
