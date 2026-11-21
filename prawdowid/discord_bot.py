"""Discord channel: a /sprawdz slash command that sends the text to the same API as the web form.

No verification logic here. The bot posts to `POST /api/checks` with `X-Channel: discord`, so web
and Discord go through the same `verify()`, and renders the returned CheckResult as Discord
Markdown. User text and source text are untrusted: Markdown and mentions are escaped and no
message can ping anyone.

Run: `make discord` (reads DISCORD_BOT_TOKEN and PRAWDOWID_API_URL from the environment).
"""

import logging
import os
import sys

import discord
import httpx2
from discord import app_commands
from discord.utils import escape_markdown, escape_mentions
from pydantic import ValidationError

from prawdowid.app import MAX_INPUT_CHARS, TECHNICAL_ERROR_MESSAGE
from prawdowid.contract import CheckResult, ClaimKind, ClaimResult, Source, Status

log = logging.getLogger("prawdowid.discord")

TOKEN_ENV = "DISCORD_BOT_TOKEN"
API_URL_ENV = "PRAWDOWID_API_URL"
CHANNEL = "discord"
# Above the API's 60 s verify limit, well inside the 15 min interaction token.
API_TIMEOUT_S = 75
MESSAGE_LIMIT = 2000  # Discord's limit for one message
MAX_MESSAGES = 5
TRUNCATED = "… Odpowiedź była za długa dla Discorda i została skrócona."
CONNECTION_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę."


def _safe(text: str) -> str:
    # One line: a line break in untrusted text must not end its quote or section.
    return escape_mentions(escape_markdown(" ".join(text.split())))


def _bullets(items: list[str]) -> list[str]:
    return [f"- {_safe(item)}" for item in items]


def _source(s: Source) -> list[str]:
    meta = ", ".join(
        part
        for part in (_safe(s.publisher), s.published_at and s.published_at.isoformat())
        if part
    )
    # <url> stops Discord from unfurling a preview of an untrusted page.
    lines = [f"- {_safe(s.title)}" + (f", {meta}" if meta else "") + f" <{s.url}>"]
    if s.fragment:
        lines.append(f"> „{_safe(s.fragment)}”")
    return lines


# Claims from a quote: who said it, and what was said. Plain statements get no tag.
KIND_LABELS = {
    ClaimKind.ATTRIBUTION: "Kto co powiedział",
    ClaimKind.QUOTED: "Treść cytatu",
}
SECURITY_NOTE = (
    "Treść zawierała polecenia skierowane do modelu. "
    "Zignorowaliśmy je i sprawdziliśmy resztę."
)
SECURITY_NOTE_ONLY = (
    "Treść zawierała polecenia skierowane do modelu. Zignorowaliśmy je."
)
SOURCE_SECURITY_NOTE = (
    "W źródłach znaleźliśmy polecenia skierowane do modelu. "
    "Zignorowaliśmy je i sprawdziliśmy resztę."
)
PAGE_NOTE = "Ta strona nie jest źródłem dowodów dla własnych twierdzeń."
UNCHECKED_NOTE = (
    "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. "
    "Tych nie oceniliśmy. Możesz wkleić je osobno."
)


def _claim(n: int, c: ClaimResult) -> str:
    kind = f"[{KIND_LABELS[c.kind]}] " if c.kind in KIND_LABELS else ""
    lines = [
        f"### {n}. {_safe(c.claim)}",
        f"-# {kind}W tekście: {_safe(c.source_sentence)}",
        f"Ocena: **{c.verdict_label}**",
        f"**Uzasadnienie:** {_safe(c.reasoning)}",
        f"**Siła dowodów:** {_safe(c.strength)}",
        "**Przesłanki:**",
        *_bullets(c.premises),
        "**Źródła:**",
        *([line for s in c.sources for line in _source(s)] or ["- brak"]),
    ]
    if c.limitations:
        lines += ["**Ograniczenia:**", *_bullets(c.limitations)]
    return "\n".join(lines)


def render(check: CheckResult) -> str:
    """CheckResult as Discord Markdown, with the same sections as the web form."""
    # Statuses other than "ok" are notices, never verdicts.
    if check.status is not Status.OK:
        notice = f"**Brak oceny.** {_safe(check.message or '')}"
        if check.security_events:
            notice = f"**Polecenia dla modelu.** {SECURITY_NOTE_ONLY}\n\n{notice}"
        return notice
    if not check.claims and not check.unchecked_claims:
        return "**Brak twierdzeń.** Usługa nie zwróciła żadnego twierdzenia."
    locations = {e.location for e in check.security_events}
    sections = [
        f"**Polecenia dla modelu.** {note}"
        for note, found in (
            (SECURITY_NOTE, locations - {"source"}),
            (SOURCE_SECURITY_NOTE, locations & {"source"}),
        )
        if found
    ]
    if check.page:
        p = check.page
        meta = ", ".join(
            part
            for part in (
                p.publisher and _safe(p.publisher),
                p.published_at and p.published_at.isoformat(),
            )
            if part
        )
        sections.insert(
            0,
            f"Sprawdzony tekst pochodzi ze strony: {_safe(p.title or p.url)}"
            + (f", {meta}" if meta else "")
            + f" <{p.url}>. {PAGE_NOTE}",
        )
    sections += [_claim(n, c) for n, c in enumerate(check.claims, 1)]
    if check.unchecked_claims:
        sections.append(
            "\n".join(
                [
                    "### Niesprawdzone twierdzenia",
                    UNCHECKED_NOTE,
                    *_bullets(check.unchecked_claims),
                ]
            )
        )
    return "\n\n".join(sections)


def split(text: str) -> list[str]:
    """Cut text into Discord messages on line breaks; at most MAX_MESSAGES, marked if cut."""
    # Hand-rolled: commands.Paginator raises on a line longer than one message.
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > MESSAGE_LIMIT:
            if current:
                parts.append(current)
            current, line = line[:MESSAGE_LIMIT], line[MESSAGE_LIMIT:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > MESSAGE_LIMIT:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    if len(parts) > MAX_MESSAGES:
        parts = parts[:MAX_MESSAGES]
        parts[-1] = parts[-1][: MESSAGE_LIMIT - len(TRUNCATED) - 1] + "\n" + TRUNCATED
    return parts


def _notice(message: str) -> CheckResult:
    return CheckResult(status=Status.TECHNICAL_ERROR, message=message)


async def ask_api(text: str, client: httpx2.AsyncClient) -> CheckResult:
    """The same request the web form sends. Any failure becomes a notice, never a verdict."""
    try:
        resp = await client.post(
            "/api/checks", json={"input": text}, headers={"X-Channel": CHANNEL}
        )
    except httpx2.HTTPError:
        log.exception("API call failed")
        return _notice(CONNECTION_ERROR)
    if resp.status_code in (422, 429):
        # Input rejected or rate limited: the API's Polish message, shown as a notice.
        try:
            detail = resp.json()["detail"]
            message = detail if isinstance(detail, str) else detail[0]["msg"]
        except (ValueError, LookupError, TypeError):
            message = TECHNICAL_ERROR_MESSAGE
        return CheckResult(status=Status.CANNOT_CHECK, message=str(message))
    try:
        resp.raise_for_status()
        return CheckResult.model_validate_json(resp.content)
    except (httpx2.HTTPError, ValidationError):
        log.exception("API answered with an error or a bad body")
        return _notice(TECHNICAL_ERROR_MESSAGE)


class Bot(discord.Client):
    def __init__(self, base_url: str) -> None:
        # Slash commands need no privileged intent (no message content).
        super().__init__(intents=discord.Intents.default())
        self.base_url = base_url
        self.api: httpx2.AsyncClient | None = None
        self.tree = app_commands.CommandTree(self)

        @self.tree.command(name="sprawdz", description="Sprawdź twierdzenia w tekście.")
        @app_commands.describe(tekst="Tekst do sprawdzenia")
        async def sprawdz(
            interaction: discord.Interaction,
            tekst: app_commands.Range[str, 1, MAX_INPUT_CHARS],
        ) -> None:
            # Acknowledge within Discord's 3 s window; the check can take up to a minute.
            await interaction.response.defer(thinking=True)
            check = await ask_api(tekst, self.api)
            log.info("check status=%s input_chars=%d", check.status, len(tekst))
            for part in split(render(check)):
                await interaction.followup.send(
                    part,
                    allowed_mentions=discord.AllowedMentions.none(),
                    suppress_embeds=True,
                )

    async def setup_hook(self) -> None:
        # Created here so the client lives in the bot's event loop.
        self.api = httpx2.AsyncClient(base_url=self.base_url, timeout=API_TIMEOUT_S)
        await self.tree.sync()

    async def close(self) -> None:
        if self.api:
            await self.api.aclose()
        await super().close()


def main() -> None:
    token = os.getenv(TOKEN_ENV)
    if not token:
        sys.exit(
            f"{TOKEN_ENV} is not set. Put the bot token in .env and start again "
            "(make discord)."
        )
    base_url = os.getenv(API_URL_ENV) or "http://127.0.0.1:8000"
    # log_handler=None: logging is already set up by prawdowid.app; avoids duplicate lines.
    Bot(base_url).run(token, log_handler=None)


if __name__ == "__main__":
    main()
