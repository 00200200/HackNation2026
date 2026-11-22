import csv
import io
import json
from datetime import UTC, date, datetime, timedelta

import pytest
import stix2
from fastapi.testclient import TestClient

from prawdowid import cases, checklog, export
from prawdowid.app import app, limiter
from prawdowid.contract import (
    CheckResult,
    ClaimKind,
    ClaimResult,
    IncidentMatch,
    MatchKind,
    Source,
    Status,
    Verdict,
)

TOKEN = "test-admin-token-0123456789"
PESEL = "44051401359"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def source(url, source_type="fact_check", publisher="Demagog", day=date(2026, 11, 1)):
    return Source(
        title="Tytuł",
        publisher=publisher,
        published_at=day,
        fetched_at=datetime.now(UTC),
        url=url,
        source_type=source_type,
    )


def claim(text="Tramwaje w Opolu są darmowe.", verdict=Verdict.FALSE, sources=()):
    return ClaimResult(
        claim=text,
        kind=ClaimKind.STATEMENT,
        source_sentence=text,
        verdict=verdict,
        reasoning="Miasto zaprzecza w komunikacie.",
        strength="",
        premises=[],
        sources=list(sources),
        limitations=["Brak danych z 2025 r."],
    )


@pytest.fixture
def client():
    limiter.reset()
    return TestClient(app)


@pytest.fixture
def full_answer():
    return CheckResult(
        status=Status.OK,
        claims=[
            claim(
                sources=[
                    source("https://demagog.org.pl/a"),
                    source(
                        "https://euvsdisinfo.eu/report/x",
                        "disinfo_database",
                        "EUvsDisinfo",
                    ),
                ]
            ),
            claim("Opinia.", Verdict.NOT_VERIFIABLE),
        ],
        incident_matches=[
            IncidentMatch(
                incident_id="INC-7",
                incident_text="Podobna plotka",
                matched_on=MatchKind.TEXT,
                similarity=0.8,
            )
        ],
    )


def parse(text):
    bundle = stix2.parse(text, allow_custom=False)
    return bundle, {
        o.type: [x for x in bundle.objects if x.type == o.type] for o in bundle.objects
    }


def test_bundle_parses_back_and_has_the_required_objects(full_answer):
    bundle, by_type = parse(export.stix_bundle(full_answer))
    [identity] = by_type["identity"]
    [report] = by_type["report"]
    notes = by_type["note"]
    assert identity.name == "faktczyfejk.pl" and identity.identity_class == "system"
    assert len(notes) == 3  # two claims and the incident context
    assert set(report.object_refs) == {identity.id, *(n.id for n in notes)}
    assert all(
        n.created_by_ref == identity.id and report.id in n.object_refs for n in notes
    )
    assert {o.id for o in bundle.objects} >= set(report.object_refs)


def test_a_note_carries_the_verdict_the_justification_and_the_sources(full_answer):
    _, by_type = parse(export.stix_bundle(full_answer))
    note = next(n for n in by_type["note"] if n.abstract.startswith("Tramwaje"))
    assert note.labels == ["verdict:false"]
    assert "fałszywe" in note.content and "Miasto zaprzecza" in note.content
    assert "Brak danych z 2025 r." in note.content
    urls = {r.url: r for r in note.external_references}
    assert set(urls) == {"https://demagog.org.pl/a", "https://euvsdisinfo.eu/report/x"}
    assert "Demagog" in urls["https://demagog.org.pl/a"].description
    assert "2026-11-01" in urls["https://demagog.org.pl/a"].description
    # EUvsDisinfo is named as context, not as evidence.
    assert "Kontekst, nie dowód" in note.content


def test_incident_matches_are_external_references(full_answer):
    _, by_type = parse(export.stix_bundle(full_answer))
    context = next(n for n in by_type["note"] if n.abstract.startswith("Matches"))
    [ref] = context.external_references
    assert ref.external_id == "INC-7"


def test_no_disarm_ids_are_invented(full_answer):
    assert "T00" not in export.stix_bundle(full_answer)
    assert "attack-pattern" not in export.stix_bundle(full_answer)


def test_the_bundle_is_masked_again():
    leaked = claim(f"Mój PESEL to {PESEL}, a to kłamstwo.")
    bundle = export.stix_bundle(CheckResult(status=Status.OK, claims=[leaked]))
    assert PESEL not in bundle


@pytest.mark.parametrize(
    "answer",
    [
        CheckResult(status=Status.OK),
        CheckResult(status=Status.TECHNICAL_ERROR, message="Błąd."),
    ],
)
def test_nothing_to_export_without_claims(answer):
    with pytest.raises(ValueError):
        export.stix_bundle(answer)


def test_stix_route_returns_a_bundle(client, full_answer):
    resp = client.post("/api/export/stix", content=full_answer.model_dump_json())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/stix+json")
    assert stix2.parse(resp.text).type == "bundle"


def test_stix_route_refuses_a_large_payload(client, full_answer):
    resp = client.post("/api/export/stix", content=b" " * (export.MAX_ANSWER_BYTES + 1))
    assert resp.status_code == 413


@pytest.mark.parametrize(
    "body", [b"not json", b'{"status": "ok"}', b'{"status":"ok","claims":[]}']
)
def test_stix_route_refuses_what_is_not_an_answer(client, body):
    assert client.post("/api/export/stix", content=body).status_code == 422


# Admin export of the check log.


def write(session, minutes_ago, **fields):
    entry = {
        "session": session,
        "time": (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
        "latency_ms": 1200,
        "channel": "web",
        "question": "Czy tramwaje są darmowe?",
        "status": "ok",
        "error": None,
        "message": None,
        "steps_ms": {},
        "model_calls": [{"model": "m", "input_tokens": 1, "output_tokens": 1}],
        "cost_usd": 0.01,
        "unpriced_requests": 0,
        "security_events": [
            {"kind": "prompt_injection", "location": "input", "detector": "patterns"}
        ],
        "incidents": ["INC-7"],
        "moderator_case": {"id": 3, "status": "created", "count": 1},
        "limitations": [],
        "claims": [
            {
                "claim": "Tramwaje są darmowe.",
                "verdict": "false",
                "sources": [{"url": "https://www.gov.pl/a", "source_type": "official"}],
                "limitations": [],
                "steps_ms": {},
            }
        ],
        "unchecked_claims": [],
        **fields,
    }
    with checklog.CHECK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv(cases.ADMIN_TOKEN_ENV, TOKEN)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_admin_export_refuses_a_missing_or_wrong_token(client, admin, headers):
    resp = client.get("/api/export/checks", headers=headers)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_admin_export_does_not_exist_without_a_configured_token(client, monkeypatch):
    monkeypatch.delenv(cases.ADMIN_TOKEN_ENV, raising=False)
    assert client.get("/api/export/checks", headers=AUTH).status_code == 404


def test_admin_export_json_has_no_session_and_no_raw_fields(client, admin):
    write("session-0001", 5)
    rows = client.get("/api/export/checks", headers=AUTH).json()
    [row] = rows
    assert set(row) == set(export.LOG_FIELDS)
    assert "session" not in row and "model_calls" not in row and "steps_ms" not in row
    assert "session-0001" not in json.dumps(rows)


def test_admin_export_csv_columns_and_one_row_per_check(client, admin):
    write("session-0001", 5)
    write("session-0002", 4, claims=[], status="technical_error", error="timeout")
    resp = client.get("/api/export/checks?format=csv", headers=AUTH)
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert tuple(rows[0]) == export.CSV_COLUMNS
    assert len(rows) == 2
    assert (
        rows[0]["verdicts"] == "false"
        and rows[0]["source_urls"] == "https://www.gov.pl/a"
    )
    assert rows[0]["security_events"] == "1" and rows[0]["moderator_case"] == "3"
    assert rows[1]["status"] == "technical_error" and rows[1]["claims"] == ""
    assert "session" not in resp.text


def test_admin_export_stores_only_masked_text(client, admin):
    q = checklog.masked_question(f"Mój PESEL {PESEL}. Czy to prawda?")
    write("session-0001", 5, question=q)
    for fmt in ("csv", "json"):
        assert (
            PESEL
            not in client.get(f"/api/export/checks?format={fmt}", headers=AUTH).text
        )


def test_admin_export_applies_retention_and_the_date_range(client, admin):
    write("s1", 60 * 24 * 40)  # 40 days ago: outside the 30 days of retention
    write("s2", 60 * 24 * 3)
    write("s3", 5)
    today = datetime.now(UTC).date()
    everything = client.get("/api/export/checks", headers=AUTH).json()
    assert len(everything) == 2
    since = (today - timedelta(days=1)).isoformat()
    assert len(client.get(f"/api/export/checks?from={since}", headers=AUTH).json()) == 1
    old = (today - timedelta(days=45)).isoformat()
    assert (
        client.get(f"/api/export/checks?from={old}&to={old}", headers=AUTH).json() == []
    )


def test_admin_export_rejects_a_bad_range_and_format(client, admin):
    assert (
        client.get(
            "/api/export/checks?from=2026-11-20&to=2026-11-01", headers=AUTH
        ).status_code
        == 422
    )
    assert (
        client.get("/api/export/checks?from=nonsense", headers=AUTH).status_code == 422
    )
    assert client.get("/api/export/checks?format=xml", headers=AUTH).status_code == 422


def test_a_spreadsheet_formula_in_a_cell_is_defused():
    row = {k: None for k in export.LOG_FIELDS} | {
        "question": '=HYPERLINK("http://x")',
        "claims": [],
    }
    out = export.log_csv([row | {"incidents": [], "security_events": []}])
    assert "'=HYPERLINK" in out


def test_the_export_is_bounded(monkeypatch):
    monkeypatch.setattr(export, "MAX_ROWS", 2)
    for i in range(4):
        write(f"s{i}", 10 - i)
    assert len(export.log_records(None, None)) == 2
