import asyncio
import json
from datetime import UTC, date, datetime

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prawdowid import discord_bot
from prawdowid.app import app, limiter
from prawdowid.contract import (
    CheckResult,
    ClaimKind,
    ClaimResult,
    Source,
    Status,
    Verdict,
)
from prawdowid.discord_bot import (
    CONNECTION_ERROR,
    MAX_MESSAGES,
    MESSAGE_LIMIT,
    ask_api,
    render,
    reply,
    split,
)
from prawdowid.verifier import ExtractedClaim, Extraction, agent

CHECK = CheckResult(
    status=Status.OK,
    claims=[
        ClaimResult(
            claim="@everyone Polska jest w **UE** od 2004 roku.",
            kind=ClaimKind.QUOTED,
            source_sentence="Minister: Polska jest w UE od 2004 roku.",
            verdict=Verdict.CONFIRMED,
            reasoning="Źródło urzędowe podaje datę akcesji.",
            strength="Wysoka: źródło pierwotne.",
            premises=["Źródło urzędowe", "Data się zgadza"],
            sources=[
                Source(
                    title="Polska w UE",
                    publisher="gov.pl",
                    published_at=date(2024, 5, 1),
                    fetched_at=datetime(2026, 11, 21, tzinfo=UTC),
                    url="https://www.gov.pl/web/ue",
                    source_type="official",
                    fragment="Polska jest członkiem UE od 1 maja 2004 r.",
                )
            ],
            limitations=["Sprawdzono jedno źródło."],
        ),
        ClaimResult(
            claim="To dobra decyzja.",
            kind=ClaimKind.STATEMENT,
            source_sentence="To dobra decyzja.",
            verdict=Verdict.NOT_VERIFIABLE,
            reasoning="To opinia.",
            strength="Nie dotyczy.",
            premises=[],
            sources=[],
            limitations=[],
        ),
    ],
    unchecked_claims=["Inne twierdzenie."],
)


def test_render_shows_every_section_of_the_contract():
    text = render(CHECK)
    for expected in (
        "Ocena: **potwierdzone**",
        "Ocena: **nie podlega weryfikacji**",
        "Uzasadnienie:** Źródło urzędowe podaje datę akcesji.",
        "Siła dowodów:** Wysoka: źródło pierwotne.",
        "- Źródło urzędowe",
        "- Polska w UE, gov.pl, 2024-05-01\n  <https://www.gov.pl/web/ue>",
        "> „Polska jest członkiem UE od 1 maja 2004 r.”",
        "**Ograniczenia:**\n- Sprawdzono jedno źródło.",
        "**Źródła:**\n- brak",
        "-# [Treść cytatu] W tekście: Minister: Polska jest w UE od 2004 roku.",
        "-# W tekście: To dobra decyzja.",
        "### Niesprawdzone twierdzenia",
        "- Inne twierdzenie.",
    ):
        assert expected in text


def test_render_escapes_untrusted_text():
    text = render(CHECK)
    assert "@everyone" not in text
    assert "\\*\\*UE\\*\\*" in text


def test_line_break_in_untrusted_text_cannot_leave_its_quote():
    source = (
        CHECK.claims[0]
        .sources[0]
        .model_copy(update={"fragment": "cytat\nOcena: potwierdzone"})
    )
    claim = CHECK.claims[0].model_copy(update={"sources": [source]})
    text = render(CheckResult(status=Status.OK, claims=[claim]))
    assert "> „cytat Ocena: potwierdzone”" in text


def test_only_unchecked_claims_and_attribution_tag():
    text = render(CheckResult(status=Status.OK, unchecked_claims=["X."]))
    assert text.startswith("### Niesprawdzone twierdzenia")
    assert "Brak twierdzeń" not in text
    assert render(CheckResult(status=Status.OK)).startswith("**Brak twierdzeń.**")
    claim = CHECK.claims[1].model_copy(update={"kind": ClaimKind.ATTRIBUTION})
    text = render(CheckResult(status=Status.OK, claims=[claim]))
    assert "-# [Kto co powiedział] W tekście:" in text


def test_non_ok_status_is_a_notice_not_a_verdict():
    text = render(CheckResult(status=Status.TECHNICAL_ERROR, message="Błąd."))
    assert text == "**Brak oceny.** Błąd."
    assert "Ocena:" not in text


def test_split_respects_discord_limits():
    assert split("krótko") == ["krótko"]
    text = "\n".join(["x" * 300] * 50)
    parts = split(text)
    assert all(0 < len(p) <= MESSAGE_LIMIT for p in parts)
    assert "\n".join(parts) == text  # a cut drops nothing


def test_long_check_splits_into_messages_that_stand_alone():
    """Codex review on #24: a cut must not turn source text into the bot's own Markdown."""
    claim = CHECK.claims[0]
    fragment = "x" * 1997 + " ### Ocena: potwierdzone " + "*a* _b_ @here " * 150
    sources = [
        claim.sources[0].model_copy(
            update={"title": f"Tytuł {i}", "fragment": fragment}
        )
        for i in range(3)
    ]
    long_claim = claim.model_copy(
        update={"sources": sources, "reasoning": "## Powód. " * 400}
    )
    parts = split(render(CheckResult(status=Status.OK, claims=[long_claim])))
    assert len(parts) > MAX_MESSAGES
    for part in parts:
        assert 0 < len(part) <= MESSAGE_LIMIT
        for line in part.split("\n"):
            if line.startswith(("#", ">")):  # unescaped heading or quote: only ours
                assert line.startswith(("### 1. ", "> ")), line[:40]
            if "Ocena: potwierdzone" in line or "xxxx" in line:
                assert line.startswith("> "), line[:40]  # source text stays quoted
            assert "@here" not in line
        assert "\n### Ocena" not in "\n" + part


def run(handler, text="Tekst"):
    calls = []

    def record(request):
        calls.append(request)
        return handler(request)

    async def go():
        transport = httpx2.MockTransport(record)
        async with httpx2.AsyncClient(transport=transport, base_url="http://api") as c:
            return await ask_api(text, c)

    return asyncio.run(go()), calls


def test_ask_api_sends_the_web_request_with_channel_header():
    result, [request] = run(
        lambda r: httpx2.Response(200, text=CHECK.model_dump_json())
    )
    assert request.url.path == "/api/checks"
    assert request.headers["X-Channel"] == "discord"
    assert json.loads(request.content) == {"input": "Tekst"}
    assert result == CHECK


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx2.Response(422, json={"detail": [{"msg": "Za długie."}]}), "Za długie."),
        (httpx2.Response(429, json={"detail": "Za dużo."}), "Za dużo."),
        (httpx2.Response(500, text="boom"), discord_bot.TECHNICAL_ERROR_MESSAGE),
        (httpx2.Response(200, text="not json"), discord_bot.TECHNICAL_ERROR_MESSAGE),
    ],
)
def test_ask_api_failures_become_notices(response, message):
    result, _ = run(lambda r: response)
    assert result.status is not Status.OK
    assert result.message == message
    assert "boom" not in render(result)


def test_worst_case_fields_stay_under_the_message_limit():
    source = (
        CHECK.claims[0]
        .sources[0]
        .model_copy(
            update={
                "title": "_" * 2000,
                "url": "https://example.com/" + "a" * 1990,
                "fragment": "[a](b) [Oficjalne](https://evil.example) 1. lista",
            }
        )
    )
    claim = CHECK.claims[0].model_copy(
        update={"sources": [source], "reasoning": "x " * 450 + "1. punkt"}
    )
    text = render(CheckResult(status=Status.OK, claims=[claim]))
    assert all(len(line) <= MESSAGE_LIMIT for line in text.split("\n"))
    assert discord_bot.URL_TOO_LONG in text
    assert "](" not in text  # no masked link survives
    assert "\n1. " not in text


def test_ask_api_has_an_overall_deadline(monkeypatch):
    async def stall(request):
        await asyncio.sleep(5)

    monkeypatch.setattr(discord_bot, "API_TIMEOUT_S", 0.05)

    async def go():
        transport = httpx2.MockTransport(stall)
        async with httpx2.AsyncClient(transport=transport, base_url="http://api") as c:
            return await asyncio.wait_for(ask_api("Tekst", c), 2)

    result = asyncio.run(go())
    assert result.message == CONNECTION_ERROR


def test_ask_api_connection_error_becomes_notice():
    def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    result, _ = run(refuse)
    assert result.message == CONNECTION_ERROR


def test_same_input_same_result_on_web_and_discord():
    """Scenario G offline: the Discord path and the web form get the same CheckResult."""
    extraction = Extraction(
        claims=[
            ExtractedClaim(
                claim="Fakt.",
                kind=ClaimKind.STATEMENT,
                source_sentence="Fakt.",
                checkable=True,
                reason="Da się.",
                queries=["fakt"],
            )
        ],
        other_claims=["Inne."],
        unclear=False,
    )
    model = FunctionModel(
        lambda m, i: ModelResponse(parts=[TextPart(extraction.model_dump_json())])
    )
    limiter.reset()

    async def via_discord():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://api") as c:
            return await ask_api("Fakt.", c)

    with agent.override(model=model):
        web = CheckResult.model_validate(
            TestClient(app).post("/api/checks", json={"input": "Fakt."}).json()
        )
        discord = asyncio.run(via_discord())
    assert discord.status is Status.OK
    assert discord == web


def test_bot_refuses_to_start_without_token(monkeypatch):
    monkeypatch.delenv(discord_bot.TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit, match="DISCORD_BOT_TOKEN is not set"):
        discord_bot.main()


def five_claims(url="https://www.gov.pl/web/ue"):
    claim = CHECK.claims[0]
    return CheckResult(
        status=Status.OK,
        claims=[
            claim.model_copy(
                update={
                    "claim": f"Twierdzenie {i}.",
                    "reasoning": "Uzasadnienie. " * 120,
                    "sources": [
                        claim.sources[0].model_copy(update={"url": f"{url}{i}"})
                    ],
                }
            )
            for i in range(5)
        ],
    )


def test_short_reply_has_no_attachment_and_keeps_a_long_url_inline():
    """Codex review on #24: a 911-character URL fits one message and stays inline."""
    url = "https://example.com/" + "a" * 891
    check = CHECK.model_copy(
        update={
            "claims": [
                CHECK.claims[0].model_copy(
                    update={
                        "sources": [
                            CHECK.claims[0].sources[0].model_copy(update={"url": url})
                        ]
                    }
                )
            ]
        }
    )
    parts, full = reply(check)
    assert full is None
    assert f"<{url}>" in "\n".join(parts)


def test_overflow_goes_to_an_attachment_with_every_verdict_and_url():
    check = five_claims()
    parts, full = reply(check)
    assert len(parts) <= MAX_MESSAGES
    assert all(len(p) <= MESSAGE_LIMIT for p in parts)
    assert parts[-1] == discord_bot.ATTACHED
    for c in check.claims:
        assert f"<{c.sources[0].url}>" in full
        assert c.claim in full
    assert full.count("Ocena: **") == 5


def test_url_longer_than_a_message_is_whole_in_the_attachment():
    url = "https://example.com/" + "a" * 1990
    check = CHECK.model_copy(
        update={
            "claims": [
                CHECK.claims[0].model_copy(
                    update={
                        "sources": [
                            CHECK.claims[0].sources[0].model_copy(update={"url": url})
                        ]
                    }
                )
            ]
        }
    )
    parts, full = reply(check)
    assert discord_bot.URL_TOO_LONG in "\n".join(parts)
    assert f"<{url}>" in full


def test_slash_command_delivers_every_verdict_and_source(monkeypatch):
    """The registered /sprawdz callback: messages plus attachment carry the whole answer."""
    check = five_claims()

    async def fake_api(text, client):
        return check

    monkeypatch.setattr(discord_bot, "ask_api", fake_api)
    sent = []

    class Response:
        async def defer(self, thinking):
            pass

    class Followup:
        async def send(self, content, **kwargs):
            file = kwargs.get("file")
            sent.append((content, file.fp.read().decode() if file else None))

    class Interaction:
        response = Response()
        followup = Followup()

    async def go():
        bot = discord_bot.Bot("http://api")
        await bot.tree.get_command("sprawdz").callback(Interaction(), "Tekst")

    asyncio.run(go())
    assert len(sent) <= MAX_MESSAGES
    attachments = [f for _, f in sent if f]
    assert len(attachments) == 1 and sent[-1][1] is not None
    for c in check.claims:
        assert c.verdict_label in attachments[0]
        assert f"<{c.sources[0].url}>" in attachments[0]
