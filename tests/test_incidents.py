"""Scenario I matcher. INCIDENTS below is a test-only fixture, never shipped as data."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prawdowid import app as app_module
from prawdowid.app import app, limiter
from prawdowid.contract import CheckResult, IncidentMatch, MatchKind, Status
from prawdowid.discord_bot import render
from prawdowid.incidents import (
    INCIDENTS_PATH,
    Incident,
    load_incidents,
    match_incidents,
)
from prawdowid.verifier import agent
from tests.test_app import MIXED

INCIDENTS = (
    Incident(
        id="TEST-1",
        text="Drony nad Polską to ukraińska prowokacja z przechwyconymi rosyjskimi dronami.",
        url="https://fake-news.example/drony?utm_source=x",
    ),
    Incident(
        id="TEST-2",
        text="Polska przejmie zachodnią Ukrainę.",
        domain="propaganda.example",
    ),
)


def test_url_match_ignores_tracking_and_www():
    [m] = match_incidents("Zobacz http://www.fake-news.example/drony/.", INCIDENTS)
    assert (m.incident_id, m.matched_on) == ("TEST-1", MatchKind.URL)


def test_domain_match_covers_subdomains():
    [m] = match_incidents("https://news.propaganda.example/a/1", INCIDENTS)
    assert (m.incident_id, m.matched_on) == ("TEST-2", MatchKind.DOMAIN)


def test_text_similarity_match_on_one_sentence_of_a_longer_text():
    text = (
        "Wczoraj był ciepły dzień. Drony nad Polską to ukraińska prowokacja "
        "z przechwyconymi rosyjskimi dronami! Tak piszą w sieci."
    )
    [m] = match_incidents(text, INCIDENTS)
    assert (m.incident_id, m.matched_on) == ("TEST-1", MatchKind.TEXT)
    assert m.similarity >= 0.9


def test_unrelated_text_and_empty_base_match_nothing():
    assert match_incidents("Polska jest w UE od 2004 roku.", INCIDENTS) == []
    assert match_incidents("https://fake-news.example/drony", ()) == []


def test_shipped_base_is_empty():
    assert load_incidents(INCIDENTS_PATH) == ()


def test_loader_reads_json_and_csv_and_survives_missing_or_broken(tmp_path):
    rows = [{"id": "A", "text": "Tekst.", "url": "https://a.example/x"}]
    (tmp_path / "b.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "b.csv").write_text(
        "id,text,url,domain\nA,Tekst.,https://a.example/x,\n", encoding="utf-8"
    )
    (tmp_path / "bom.csv").write_text(
        "\ufeffid,text,url\nA,Tekst.,https://a.example/x\n", encoding="utf-8"
    )
    (tmp_path / "bad.json").write_text("{nie json", encoding="utf-8")
    (tmp_path / "obj.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "rows.json").write_text(
        json.dumps(["x", {"id": 7, "text": "T."}, {"id": "B"}]), encoding="utf-8"
    )
    expected = (Incident(**rows[0]),)
    for name in ("b.json", "b.csv", "bom.csv"):
        assert load_incidents(str(tmp_path / name)) == expected
    for name in ("bad.json", "obj.json", "missing.json"):
        assert load_incidents(str(tmp_path / name)) == ()
    # Bad rows are skipped, numeric ids become strings.
    assert load_incidents(str(tmp_path / "rows.json")) == (Incident(id="7", text="T."),)


def test_malformed_urls_and_domain_forms():
    bad = (Incident(id="U", text="X.", url="http://[x"),)
    assert match_incidents("Zobacz http://[abc i tyle.", INCIDENTS + bad) == []
    base = (Incident(id="D", text="X.", domain="https://www.Propaganda.example/"),)
    [m] = match_incidents("https://propaganda.example/a", base)
    assert m.matched_on == MatchKind.DOMAIN


@pytest.fixture
def client(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(
        app_module, "match_incidents", lambda text: match_incidents(text, INCIDENTS)
    )
    model = FunctionModel(
        lambda messages, info: ModelResponse(parts=[TextPart(MIXED.model_dump_json())])
    )
    with agent.override(model=model):
        yield TestClient(app)


def _check(client, text):
    resp = client.post("/api/checks", json={"input": text})
    assert resp.status_code == 200
    return resp.json()


def test_match_is_a_separate_field_and_verdicts_stay_the_same(client):
    plain = _check(client, "Fakt. Opinia.")
    matched = _check(
        client, "Drony nad Polską to ukraińska prowokacja z rosyjskimi dronami."
    )
    assert plain["incident_matches"] == []
    assert [m["incident_id"] for m in matched["incident_matches"]] == ["TEST-1"]
    assert matched["claims"] == plain["claims"]


def test_link_keeps_its_notice_and_shows_the_match(client):
    body = _check(client, "https://fake-news.example/drony")
    assert body["status"] == "cannot_check"
    assert body["claims"] == []
    assert body["incident_matches"][0]["matched_on"] == "url"


def test_discord_renders_the_warning_only_when_there_is_a_match():
    check = CheckResult(status=Status.CANNOT_CHECK, message="Nie obsługujemy linków.")
    assert "incydent" not in render(check)
    check.incident_matches = [
        IncidentMatch(
            incident_id="TEST-1",
            incident_text="Drony to prowokacja.",
            matched_on=MatchKind.TEXT,
            url="https://fake-news.example/drony",
            similarity=0.81,
        )
    ]
    text = render(check)
    assert "### Podobne znane incydenty" in text
    assert (
        "- Drony to prowokacja. (TEST-1, podobny tekst 81%) <https://fake-news.example/drony>"
        in text
    )
    assert "nie zmienia oceny" in text
