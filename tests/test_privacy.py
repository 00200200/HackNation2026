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
WHEN = {"started_at": datetime.now(UTC), "latency_ms": 1}
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


@pytest.mark.usefixtures("quiet_sources")
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
    checklog.record("new-0001", "web", "pytanie", result, **WHEN)
    assert [r["session"] for r in records(check_log)] == ["new-0001"]


def test_damaged_lines_never_block_logging_or_deletion(check_log):
    check_log.write_text('not json\n1\n{"session": "s-000001"}\n')
    checklog.record(
        "s-000001",
        "web",
        "pytanie",
        CheckResult(status=Status.TECHNICAL_ERROR, message="x"),
        **WHEN,
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
    save_document(page("https://gov.pl/x", 0), again)
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
    checklog.record("gone-0001", "web", "pytanie", result, **WHEN)

    def write(i):
        if i % 5 == 0:
            checklog.delete_session("gone-0001")
        checklog.record(f"s-{i:06d}", "web", "pytanie", result, **WHEN)

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
            type(
                "S",
                (),
                {
                    "url": "https://example.org/?mail=jan.kowalski@example.com",
                    "source_type": "news",
                },
            )
        ],
        limitations=[f"PESEL {PESEL}"],
    )
    result = CheckResult.model_construct(
        status=Status.OK, claims=[claim], unchecked_claims=[f"tel. {PHONE}"]
    )
    checklog.record("s-000001", "web", "pytanie", result, **WHEN)
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


def test_a_check_running_during_deletion_is_not_written(check_log):
    started = datetime.now(UTC)
    assert checklog.delete_session("s-000001") == 0
    result = CheckResult(status=Status.TECHNICAL_ERROR, message="x")
    checklog.record(
        "s-000001", "web", "pytanie", result, started_at=started, latency_ms=1
    )
    assert records(check_log) == []
    # A check started after the deletion is written again.
    checklog.record(
        "s-000001",
        "web",
        "pytanie",
        result,
        **{**WHEN, "started_at": datetime.now(UTC)},
    )
    assert [r["session"] for r in records(check_log)] == ["s-000001"]


# Identifiers added for #82; every number is synthetic. The ID card has a valid check digit.
NEW_IDENTIFIERS = [
    ("ABA300000", "[numer dowodu]"),
    ("ABA 300000", "[numer dowodu]"),
    ("AB1234567", "[numer paszportu]"),
    ("600 123 456", "[telefon]"),
    ("600123456", "[telefon]"),
    ("+48600123456", "[telefon]"),
    ("(+48) 600 123 456", "[telefon]"),
]


@pytest.mark.parametrize(("raw", "placeholder"), NEW_IDENTIFIERS)
def test_new_identifiers_are_masked_before_the_model_and_in_the_logs(
    client, check_log, caplog, raw, placeholder
):
    api, sent = client
    question = (
        f"Donald Tusk powiedział, że jego numer to {raw}, a PKB Polski wzrósł o 3%."
    )
    with caplog.at_level(logging.INFO, logger="prawdowid"):
        assert api.post("/api/checks", json={"input": question}).status_code == 200
    masked = question.replace(raw, placeholder)
    [rec] = records(check_log)
    assert rec["question"] == masked
    # The model gets the masked sentence, with the public figure's name in it.
    assert masked in sent[0]
    for text in [check_log.read_text(), caplog.text, *sent]:
        assert raw not in text


@pytest.mark.parametrize(("raw", "placeholder"), NEW_IDENTIFIERS)
def test_an_exception_carrying_a_new_identifier_is_logged_masked(
    client, caplog, monkeypatch, raw, placeholder
):
    import prawdowid.app as app_module

    async def broken(text):
        raise RuntimeError(f"fetch failed for {raw}")

    monkeypatch.setattr(app_module, "verify", broken)
    api, _ = client
    with caplog.at_level(logging.INFO, logger="prawdowid"):
        api.post("/api/checks", json={"input": "PKB Polski wzrósł o 3%."})
    assert f"fetch failed for {placeholder}" in caplog.text
    assert raw not in caplog.text


@pytest.mark.parametrize(("raw", "placeholder"), NEW_IDENTIFIERS)
def test_the_logging_filter_masks_new_identifiers(raw, placeholder):
    import sys

    from prawdowid.privacy import MaskingFilter

    try:
        raise RuntimeError(f"lookup failed for {raw}")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "prawdowid", logging.ERROR, "", 0, "check of %s failed", (raw,), exc_info
    )
    assert MaskingFilter().filter(record) is True
    assert record.getMessage() == f"check of {placeholder} failed"
    assert placeholder in record.exc_text and raw not in record.exc_text


@pytest.mark.parametrize("number", ["ABA300000", "ABA 300000"])
def test_an_id_card_number_with_a_valid_check_digit_is_masked(number):
    text = f"dowód osobisty {number}, wydany w 2019 roku"
    assert mask_personal_data(text) == (
        "dowód osobisty [numer dowodu], wydany w 2019 roku"
    )


# Vectors from other projects' tests (polish-validators, polish-id-card-validate, Faker), so the check
# digit is not only checked against our own reading of it.
@pytest.mark.parametrize(
    "number", ["ABC412345", "ABS123456", "AIS850214", "AUL927285", "AEI251824"]
)
def test_id_card_numbers_other_projects_call_valid_are_masked(number):
    assert mask_personal_data(f"dowód {number}.") == "dowód [numer dowodu]."


@pytest.mark.parametrize("number", ["ABC512345", "ABS523456"])
def test_id_card_numbers_other_projects_call_invalid_stay(number):
    assert mask_personal_data(f"dowód {number}.") == f"dowód {number}."


def test_a_passport_number_is_masked():
    assert mask_personal_data("paszport AB1234567.") == "paszport [numer paszportu]."


@pytest.mark.parametrize(
    "text",
    [
        "kod ABA300001",  # wrong check digit
        "kwota PLN 123456",  # passes the check digit, but is a currency code
        "dla 100000 osób",  # lower case is no ID card
        "faktura nr 1234567",  # passports have no space
        "faktura nr1234567",
        "dotacja z NFZ 100000 zł",  # passes the check digit, but a currency follows
        "ZUS 300000 zł",
        "GUS 550000 osób",
        "KRS 0000123456",
    ],
)
def test_codes_that_are_not_id_cards_or_passports_stay(text):
    assert mask_personal_data(text) == text


@pytest.mark.parametrize(
    "phone",
    [
        "600 123 456",
        "600123456",
        "+48600123456",
        "(+48) 600 123 456",
        "+48 600 123 456",
        "+48 600123456",
        "(48) 600 123 456",
        "0048 600 123 456",
        "600-123-456",
        "600\N{NO-BREAK SPACE}123\N{NO-BREAK SPACE}456",
        "600 12 34 56",
        "+48 600 12 34 56",
        "502 123 456",
    ],
)
def test_phone_formats(phone):
    assert mask_personal_data(f"Zadzwoń na {phone}.") == "Zadzwoń na [telefon]."


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("Infolinia 24/7 +48 600 100 200", "Infolinia 24/7 [telefon]"),
        ("+48 600 100 200 +48 601 200 300", "[telefon] [telefon]"),
        (
            "Infolinia +48 600 100 200 7 dni w tygodniu",
            "Infolinia [telefon] 7 dni w tygodniu",
        ),
        ("Tel+48600100200", "Tel[telefon]"),
        ("Infolinia 600 100 200 24 godziny", "Infolinia [telefon] 24 godziny"),
    ],
)
def test_a_phone_next_to_other_numbers_is_masked(text, masked):
    assert mask_personal_data(text) == masked


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("tel. 22 123 45 67", "tel. [telefon]"),
        ("tel. nr 22 123 45 67", "tel. nr [telefon]"),
        ("tel: 221234567", "tel: [telefon]"),
        ("Telefon 12 345 67 89", "Telefon [telefon]"),
        ("+48 22 123 45 67", "[telefon]"),
        ("+48 (22) 123 45 67", "[telefon]"),
        ("(22) 123-45-67", "[telefon]"),
        ("phone=123456789", "phone=[telefon]"),
    ],
)
def test_a_landline_is_masked_in_brackets_or_after_a_label_or_a_country_code(
    text, masked
):
    assert mask_personal_data(text) == masked


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("tel. 600 100 000", "tel. [telefon]"),  # ends in 000, but a label says phone
        ("https://x.pl/?phone=600123456", "https://x.pl/?phone=[telefon]"),
    ],
)
def test_a_label_wins_over_the_round_number_and_url_exclusions(text, masked):
    assert mask_personal_data(text) == masked


def test_every_number_of_a_list_is_masked():
    text = "tel. 600 123 456, 601 234 567 lub 602-345-678"
    assert mask_personal_data(text) == "tel. [telefon], [telefon] lub [telefon]"


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("600-100-200 601-200-300", "[telefon] [telefon]"),
        ("ul. Długa 5 600-100-200", "ul. Długa 5 [telefon]"),
        ("600-100-200 2024", "[telefon] 2024"),
        ("+48 600-100-200", "[telefon]"),
    ],
)
def test_a_dashed_phone_is_masked_next_to_other_numbers(text, masked):
    assert mask_personal_data(text) == masked


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        (
            "numer telefonu 600 123 456 osoby, która dzwoniła",
            "numer telefonu [telefon] osoby, która dzwoniła",
        ),
        ("tel. 600 123 456 osób", "tel. [telefon] osób"),
        ("dowód ABA300000 osoby zmarłej", "dowód [numer dowodu] osoby zmarłej"),
    ],
)
def test_a_count_word_does_not_hide_a_labelled_phone_or_a_glued_id_card(text, masked):
    assert mask_personal_data(text) == masked


@pytest.mark.parametrize(
    "text",
    [
        "123456789 zł",
        "Dz.U. 2024 poz. 123",
        "w 2024 roku 1500 osób",
        "500 000 000 zł",  # mobile-like prefix, currency behind
        "wydano 600123456 złotych",
        "600 000 000 dolarów",
        "budżet 450 mln",
        "UE liczy 450 000 000 mieszkańców",  # a round number: ends in 000
        "zarejestrowano 512 345 678 osób",  # a mobile prefix, but a count behind it
        "Na CPK wydano już 500 000 000, a lotniska nie ma",
        "budżet PLN 600 000 000",  # a currency in front
        "600 000 000 €",
        "€600 000 000",
        "PLN 612 345 678",
        "1 600 123 456 zł",  # the tail of a longer number
        "600 123 456 789 zł",  # the head of one
        "kwota 600123456,50 zł",
        "kwota 600123456.50",
        "https://www.example.pl/artykul/600123456",
        "https://www.example.pl/?id=600123456&a=1",
        "https://www.example.pl/tytul,600123456.html",
        "www.example.pl/a/600123456",
        "gus-532015686e",  # a mobile prefix, but a letter behind the digits: an id
        "Liczba telefonów 226 000 000 sztuk",  # a label word, but a round number and a count
        "Regon 363190367",  # nine digits, no mobile prefix
        "REGON 730123456",  # a mobile prefix, but a REGON label
        "REGON: 730 123 456",
        "NIP 123-456-78-90",
        "22 123 45 67",  # a landline needs a country code, brackets or a label
        "600\n123\n456",  # three lines are three numbers
    ],
)
def test_amounts_years_statutes_and_ids_in_urls_stay(text):
    assert mask_personal_data(text) == text


def test_names_of_public_figures_stay():
    text = "Donald Tusk powiedział, że Karol Nawrocki zawetował ustawę w 2025 roku."
    assert mask_personal_data(text) == text


def test_a_currency_code_hides_an_id_card_only_when_a_space_follows_it():
    assert mask_personal_data("kwota PLN 123456") == "kwota PLN 123456"
    assert mask_personal_data("dowód PLN123456") == "dowód [numer dowodu]"


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("tel. 600123456 44051401359", "tel. [telefon] [PESEL]"),
        ("tel. 600 123 456 2024", "tel. [telefon] 2024"),
    ],
)
def test_a_labelled_phone_is_masked_whatever_digits_follow_it(text, masked):
    assert mask_personal_data(text) == masked


def test_a_long_url_keeps_its_numeric_path_component():
    url = "https://example.pl/" + "a" * 201 + "/600123456"
    assert mask_personal_data(url) == url
    assert mask_personal_data(f"tel. {url}") == f"tel. {url}"
    assert mask_personal_data("tel. 600123456 /x") == "tel. [telefon] /x"
