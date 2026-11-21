import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prawdowid import checklog
from prawdowid.app import app, limiter
from prawdowid.contract import CheckResult, ClaimKind, Status
from prawdowid.privacy import RETENTION_DAYS, mask_personal_data
from prawdowid.verifier import ExtractedClaim, Extraction, agent

PESEL = "44051401359"
PHONE = "+48 600 100 200"
TEXT = (
    f"Jan Kowalski, PESEL {PESEL}, tel. {PHONE}, twierdzi, że PKB Polski wzrósł o 3%."
)


@pytest.fixture
def client():
    """API with a fake model that records what it was sent."""
    limiter.reset()
    sent = []

    def answer(messages, info):
        sent.append(str(messages))
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
        )
        return ModelResponse(parts=[TextPart(out.model_dump_json())])

    with agent.override(model=FunctionModel(answer)):
        yield TestClient(app), sent


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_cards_ibans_and_amounts():
    text = (
        "Karta 4111 1111 1111 1111, konto DE89 3704 0044 0532 0130 00. "
        "Budżet 1 234 567 890 123 zł, numer 4111 1111 1111 1112."
    )
    masked = mask_personal_data(text)
    assert "4111 1111 1111 1111" not in masked and "DE89" not in masked
    # Grouped amounts and digits failing Luhn stay.
    assert "1 234 567 890 123 zł, numer 4111 1111 1111 1112." in masked


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("karta 4111 1111 1111 1111 123", "karta [numer karty] 123"),
        ("karta 4111-1111-1111-1111-123", "karta [numer karty]-123"),
        ("IBAN BE68 5390 0754 7034 123", "IBAN [numer konta] 123"),
        ("IBAN AT61 1904 3002 3457 3201 EUR", "IBAN [numer konta] EUR"),
    ],
)
def test_a_trailing_token_does_not_hide_a_number(text, masked):
    assert mask_personal_data(text) == masked


def test_pesel_and_phone_masked_in_log_and_before_the_model(client, check_log, caplog):
    api, sent = client
    with caplog.at_level(logging.INFO, logger="prawdowid"):
        resp = api.post("/api/checks", json={"input": TEXT})
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    [rec] = records(check_log)
    assert rec["question"].startswith("Jan Kowalski, PESEL [PESEL], tel. [telefon],")
    assert rec["session"] == resp.headers["X-Session-Id"]
    for text in [check_log.read_text(), caplog.text, *sent]:
        assert PESEL not in text and "600 100 200" not in text


def test_session_can_be_deleted(client, check_log):
    api, _ = client
    mine = {"X-Session-Id": "demo-session-1"}
    api.post("/api/checks", json={"input": TEXT}, headers=mine)
    api.post("/api/checks", json={"input": TEXT}, headers=mine)
    api.post("/api/checks", json={"input": TEXT}, headers={"X-Session-Id": "other-01"})
    resp = api.delete("/api/sessions/demo-session-1")
    assert resp.status_code == 200 and resp.json() == {"deleted": 2}
    assert [r["session"] for r in records(check_log)] == ["other-01"]
    # Deleting again, or a session that never existed, deletes nothing.
    assert api.delete("/api/sessions/demo-session-1").json() == {"deleted": 0}
    assert api.delete("/api/sessions/bad").status_code == 422


def test_invalid_session_header_gets_a_new_id(client):
    api, _ = client
    resp = api.post("/api/checks", json={"input": TEXT}, headers={"X-Session-Id": "x"})
    assert resp.headers["X-Session-Id"] != "x"


def test_records_past_retention_are_dropped(check_log):
    old = datetime.now(UTC) - timedelta(days=RETENTION_DAYS, seconds=1)
    check_log.write_text(
        json.dumps({"session": "old-0001", "time": old.isoformat()}) + "\n"
    )
    result = CheckResult(status=Status.TECHNICAL_ERROR, message="x")
    checklog.record("new-0001", "web", "pytanie", result)
    assert [r["session"] for r in records(check_log)] == ["new-0001"]


def test_damaged_lines_never_block_logging_or_deletion(check_log):
    check_log.write_text('not json\n1\n{"session": "s-000001"}\n')
    checklog.record(
        "s-000001",
        "web",
        "pytanie",
        CheckResult(status=Status.TECHNICAL_ERROR, message="x"),
    )
    assert [r["session"] for r in records(check_log)] == ["s-000001"]
    assert checklog.delete_session("s-000001") == 1


def test_cached_pages_past_retention_are_dropped(tmp_path):
    from prawdowid.cache import Document, load_documents, save_document

    def page(url, age_days):
        return Document(
            url=url,
            title="t",
            publisher="p",
            published_at="2026-01-01",
            fetched_at=datetime.now(UTC) - timedelta(days=age_days),
            source_type="official",
            domain="gov.pl",
            text="x",
        )

    path = tmp_path / "docs.jsonl"
    save_document(page("https://gov.pl/old", RETENTION_DAYS + 1), path)
    save_document(page("https://gov.pl/kept", 1), path)
    save_document(page("https://gov.pl/new", 0), path)
    assert [d.url for d in load_documents(path)] == [
        "https://gov.pl/kept",
        "https://gov.pl/new",
    ]
    # A page past retention fetched again replaces the old copy.
    again = tmp_path / "again.jsonl"
    save_document(page("https://gov.pl/x", RETENTION_DAYS + 1), again)
    assert save_document(page("https://gov.pl/x", 0), again) is True
    [d] = load_documents(again)
    assert d.fetched_at > datetime.now(UTC) - timedelta(days=1)


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        (
            "ES91 2100 0418 4502 0005 1332 BANK NAME",
            "[numer konta] BANK NAME",
        ),
        ("BE71 0961 2345 6769 BANK NAME", "[numer konta] BANK NAME"),
        ("BE71 0961 2345 6769 AB CD EF", "[numer konta] AB CD EF"),
    ],
)
def test_words_after_an_iban_do_not_hide_it(text, masked):
    assert mask_personal_data(text) == masked


def test_concurrent_writers_keep_every_record(check_log):
    from concurrent.futures import ThreadPoolExecutor

    result = CheckResult(status=Status.TECHNICAL_ERROR, message="x")
    checklog.record("gone-0001", "web", "pytanie", result)

    def write(i):
        if i % 5 == 0:
            checklog.delete_session("gone-0001")
        checklog.record(f"s-{i:06d}", "web", "pytanie", result)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(write, range(40)))  # re-raises a delete_session crash
    sessions = [r["session"] for r in records(check_log)]
    assert sorted(sessions) == [f"s-{i:06d}" for i in range(40)]


def test_claims_and_sources_are_masked_in_the_check_log(check_log):
    from prawdowid.contract import ClaimResult

    claim = ClaimResult.model_construct(
        claim=f"PESEL {PESEL} należy do posła.",
        verdict="unverified",
        sources=[
            type("S", (), {"url": "https://example.org/?mail=jan.kowalski@example.com"})
        ],
    )
    result = CheckResult.model_construct(
        status=Status.OK, claims=[claim], unchecked_claims=[f"tel. {PHONE}"]
    )
    checklog.record("s-000001", "web", "pytanie", result)
    text = check_log.read_text()
    assert (
        PESEL not in text and "jan.kowalski" not in text and "600 100 200" not in text
    )


def test_an_unexpected_exception_is_logged_masked(
    client, check_log, caplog, monkeypatch
):
    import prawdowid.app as app_module

    async def broken(text):
        raise RuntimeError(f"fetch failed https://x.pl/?u=jan@example.com {PESEL}")

    monkeypatch.setattr(app_module, "verify", broken)
    api, _ = client
    with caplog.at_level(logging.INFO, logger="prawdowid"):
        api.post("/api/checks", json={"input": TEXT})
    assert "verify failed" in caplog.text and "RuntimeError" in caplog.text
    assert "jan@example.com" not in caplog.text and PESEL not in caplog.text


def test_a_broken_log_call_is_not_raised_by_the_filter():
    from prawdowid.privacy import MaskingFilter

    for msg, args in [
        ("x=%d", (PESEL,)),
        ("x=%d", ("a\n" + PESEL,)),
        ("x=%d", (["a\n" + PESEL],)),
        ("%(x)s", ({"y": PESEL},)),
        ("query=%r", ("a\n" + PESEL,)),  # a valid call: repr escapes the newline
    ]:
        record = logging.LogRecord("prawdowid", logging.INFO, "", 0, msg, args, None)
        assert MaskingFilter().filter(record) is True
        assert PESEL not in record.getMessage()
