"""Discord channel: a /sprawdz slash command that sends the text, and an attached image if there
is one, to the same API as the web form.

No verification logic here. The bot posts to `POST /api/checks` with `X-Channel: discord`, so web
and Discord go through the same `verify()`, and renders the returned CheckResult as Discord
Markdown. User text and source text are untrusted: Markdown and mentions are escaped and no
message can ping anyone.

Run: `make discord` (reads DISCORD_BOT_TOKEN and PRAWDOWID_API_URL from the environment).
"""

import asyncio
import base64
import io
import logging
import os
import re
import sys
import textwrap

import aiohttp
import discord
import httpx2
from discord import app_commands
from discord.utils import escape_markdown, escape_mentions
from pydantic import ValidationError

from prawdowid import image_input
from prawdowid.app import MAX_INPUT_CHARS, TECHNICAL_ERROR_MESSAGE
from prawdowid.contract import (
    CheckedPage,
    CheckResult,
    ClaimKind,
    ClaimResult,
    IncidentMatch,
    MatchKind,
    Source,
    SourceStance,
    Status,
    Verdict,
)
from prawdowid.privacy import MaskingFilter

log = logging.getLogger("prawdowid.discord")
log.addFilter(MaskingFilter())  # logger filters do not apply to child loggers

TOKEN_ENV = "DISCORD_BOT_TOKEN"
API_URL_ENV = "PRAWDOWID_API_URL"
CHANNEL = "discord"
# Above the API's 60 s verify limit, well inside the 15 min interaction token.
API_TIMEOUT_S = 75
MESSAGE_LIMIT = 2000  # Discord's limit for one message
MAX_MESSAGES = 5
ATTACHED = (
    "Dalsza część odpowiedzi nie mieści się w wiadomościach Discorda. "
    "Pełna odpowiedź, ze wszystkimi ocenami i linkami, jest w załączniku."
)
ATTACHMENT_NAME = "odpowiedz.md"
ATTACHMENT_FAILED = "Nie udało się dołączyć pliku z pełną odpowiedzią. Sprawdź ten tekst w formularzu WWW."
# Raw characters per line before escaping; escaping at most doubles them, so a line stays
# under MESSAGE_LIMIT with its prefix.
WRAP_WIDTH = 900
# "  <" + url + ">" must fit one message.
URL_LIMIT = MESSAGE_LIMIT - 4
URL_TOO_LONG = "  (link za długi na wiadomość Discorda; jest w załączniku)"
CONNECTION_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę."
# A source we know only from the search provider's result (`Source.snippet_only` says why).
SNIPPET_LABEL = "fragment z wyników wyszukiwarki"
# An image attached to /sprawdz (scenario F): checked here only by its declared type and size,
# so a file the API would refuse is not downloaded; the API checks the file itself again.
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
DOWNLOAD_TIMEOUT_S = 15
ATTACHMENT_UNREAD = (
    "Nie udało się pobrać obrazu z Discorda. Spróbuj ponownie za chwilę."
)
NOTHING_TO_CHECK = "Wpisz tekst albo dołącz obraz do sprawdzenia."


def _escape(text: str) -> str:
    text = escape_markdown(text)
    # escape_markdown escapes only the first "[x](y)" of a run; break every masked link,
    # and a leading "1." so a wrapped line cannot become a numbered list.
    text = re.sub(r"^(\d+)\.", r"\1\\.", text.replace("](", "]\\("))
    return escape_mentions(text)


def _field(prefix: str, raw: str, cont: str = "", suffix: str = "") -> list[str]:
    """One untrusted field as Discord lines that each stand alone.

    The raw text is collapsed to one line, wrapped at spaces, and only then escaped, so every
    line start is escaped and no escape sequence is cut. Continuation lines repeat `cont`
    (e.g. "> " for a quote), so a message cut between lines keeps its quote or section.
    """
    chunks = textwrap.wrap(" ".join(raw.split()), WRAP_WIDTH) or [""]
    lines = [(cont if i else prefix) + _escape(chunk) for i, chunk in enumerate(chunks)]
    lines[-1] += suffix
    return lines


def _bullets(items: list[str]) -> list[str]:
    return [line for item in items for line in _field("- ", item, "  ")]


def _source(s: Source, url_limit: int | None) -> list[str]:
    # The same labels as the web form: an undated source and a search snippet say so.
    meta = ", ".join(
        part
        for part in (
            s.publisher,
            str(s.published_at) if s.published_at else "bez daty publikacji",
            s.snippet_only and f"{SNIPPET_LABEL}; {s.snippet_only}",
        )
        if part
    )
    lines = _field("- ", f"{s.title}, {meta}" if meta else s.title, "  ")
    # Own line, <url> stops Discord from unfurling a preview of an untrusted page.
    url = str(s.url)
    fits = url_limit is None or len(url) <= url_limit
    lines.append(f"  <{url}>" if fits else URL_TOO_LONG)
    # A fact-checker's rating comes from its ClaimReview record: never shown as a page quote.
    if s.rating:
        lines += _field(RATING_LABEL, s.rating, "  ")
    elif s.fragment:
        lines += _field("> „", s.fragment, "> ", "”")
    return lines


# The evidence chain (#78): sources grouped by the side their verified quote stands on
# (`Source.stance`), in the words and order of the web form and /czat. A source the verdict rules
# set aside has no stance; an answer with no stance at all keeps one plain list.
SIDES = {
    SourceStance.SUPPORTS: "Potwierdza",
    SourceStance.REFUTES: "Przeczy",
    SourceStance.CONTEXT: "Uzupełnia kontekst",
    None: "Nie wpływa na ocenę",
}
NOT_COUNTED_NOTE = (
    "Na przykład sam nagłówek albo starsza ocena tego samego fact-checkera."
)


def _sources(sources: list[Source], url_limit: int | None) -> list[str]:
    if not any(s.stance for s in sources):
        return [line for s in sources for line in _source(s, url_limit)] or ["- brak"]
    lines = []
    for stance, name in SIDES.items():
        if side := [s for s in sources if s.stance == stance]:
            lines.append(f"__{name}__")
            if stance is None:
                lines.append(f"-# {NOT_COUNTED_NOTE}")
            lines += [line for s in side for line in _source(s, url_limit)]
    return lines


def _page(p: CheckedPage, url_limit: int | None) -> list[str]:
    """The page behind a link: what was read, not evidence for its own claims."""
    meta = ", ".join(
        part for part in (p.publisher, p.published_at and str(p.published_at)) if part
    )
    title = p.title or p.url
    lines = _field(
        "Sprawdzony tekst pochodzi ze strony: ", f"{title}, {meta}" if meta else title
    )
    fits = url_limit is None or len(p.url) <= url_limit
    lines.append(f"  <{p.url}>" if fits else URL_TOO_LONG)
    return lines + [PAGE_NOTE]


# Claims from a quote: who said it, and what was said. Plain statements get no tag.
KIND_LABELS = {
    ClaimKind.ATTRIBUTION: "Kto co powiedział",
    ClaimKind.QUOTED: "Treść cytatu",
}
SECURITY_NOTE = (
    "W treści są zwroty, które wyglądają na polecenia dla modelu. "
    "Nie wykonaliśmy ich i sprawdziliśmy resztę."
)
SECURITY_NOTE_ONLY = (
    "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich."
)
SOURCE_SECURITY_NOTE = (
    "W źródłach są zwroty, które wyglądają na polecenia dla modelu. "
    "Nie wykonaliśmy ich i sprawdziliśmy resztę."
)
PAGE_NOTE = "Ta strona nie jest źródłem dowodów dla własnych twierdzeń."
RATING_LABEL = "  Ocena fact-checkera: "
UNCHECKED_NOTE = (
    "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. "
    "Tych nie oceniliśmy. Możesz wkleić je osobno."
)


def _claim(n: int, c: ClaimResult, url_limit: int | None) -> str:
    kind = f"[{KIND_LABELS[c.kind]}] " if c.kind in KIND_LABELS else ""
    lines = [
        *_field(f"### {n}. ", c.claim, "### "),
        *_field(f"-# {kind}W tekście: ", c.source_sentence, "-# "),
        # "nie sprawdzono" is no verdict: it must not read like one.
        f"{'Bez oceny' if c.verdict is Verdict.NOT_CHECKED else 'Ocena'}: **{c.verdict_label}**",
        *_field("**Uzasadnienie:** ", c.reasoning),
        *_field("**Siła dowodów:** ", c.strength),
        "**Przesłanki:**",
        *_bullets(c.premises),
        "**Źródła:**",
        *_sources(c.sources, url_limit),
    ]
    if c.limitations:
        lines += ["**Ograniczenia:**", *_bullets(c.limitations)]
    return "\n".join(lines)


# Scenario I: a known incident the input looks like. Context only, never a verdict.
MATCH_LABELS = {
    MatchKind.URL: "ten sam adres",
    MatchKind.DOMAIN: "domena z bazy",
    MatchKind.TEXT: "podobny tekst",
}
PLAIN_URL = re.compile(r"https?://[^\s<>]+")
INCIDENT_NOTE = (
    "Ta treść przypomina incydenty z bazy organizatora. "
    "To tylko kontekst: nie zmienia oceny twierdzeń."
)


def _incident(m: IncidentMatch, url_limit: int | None) -> list[str]:
    how = MATCH_LABELS[m.matched_on]
    if m.similarity is not None:
        how += f" {round(m.similarity * 100)}%"
    lines = _field("- ", f"{m.incident_text} ({m.incident_id}, {how})", "  ")
    # The base is outside data: only a plain http(s) URL, so it cannot break out of <...>.
    if m.url and PLAIN_URL.fullmatch(m.url):
        fits = url_limit is None or len(m.url) <= url_limit
        lines.append(f"  <{m.url}>" if fits else URL_TOO_LONG)
    return lines


def _incidents(matches: list[IncidentMatch], url_limit: int | None) -> str:
    lines = [line for m in matches for line in _incident(m, url_limit)]
    return "\n".join(["### Podobne znane incydenty", INCIDENT_NOTE, *lines])


# Scenario H: the API sets `moderator_case` only once the case is stored, so this is never said
# about a hand-off that did not happen.
MODERATOR_NOTE = "Zgłoszenie trafiło do kolejki moderatora"


def _image(check: CheckResult, with_limits: bool) -> list[str]:
    """The text read from an image, above the claims: what was checked, not evidence. On a
    notice the limitations are already listed under it."""
    image = check.image
    if not image or not image.text:
        return []
    lines = ["### Odczytany tekst", *_field("> ", image.text, "> ")]
    if image.visible_date:
        lines += _field("Data widoczna na obrazie: ", image.visible_date)
    exif = ", ".join(
        part
        for part in (
            image.taken_at and f"zrobiono {image.taken_at}",
            image.camera and f"aparat {image.camera}",
        )
        if part
    )
    if exif:
        lines += _field("Metadane EXIF: ", exif)
    if with_limits and check.limitations:
        lines += ["**Ograniczenia:**", *_bullets(check.limitations)]
    return ["\n".join(lines)]


def _moderator(check: CheckResult) -> list[str]:
    case = check.moderator_case
    return [f"{MODERATOR_NOTE} (sprawa {case.id})."] if case else []


def render(check: CheckResult, url_limit: int | None = URL_LIMIT) -> str:
    """CheckResult as Discord Markdown, with the same sections as the web form.

    `url_limit=None` keeps every URL whole, for the attachment.
    """
    warning = (
        [_incidents(check.incident_matches, url_limit)]
        if check.incident_matches
        else []
    )
    # Statuses other than "ok" are notices, never verdicts.
    if check.status is not Status.OK:
        notice = "\n".join(_field("**Brak oceny.** ", check.message or ""))
        if check.security_events:
            notice = f"**Polecenia dla modelu.** {SECURITY_NOTE_ONLY}\n\n{notice}"
        if check.limitations:
            notice += "\n**Ograniczenia:**\n" + "\n".join(_bullets(check.limitations))
        return "\n\n".join(
            [notice, *_image(check, False), *warning, *_moderator(check)]
        )
    if not check.claims and not check.unchecked_claims:
        notice = "**Brak twierdzeń.** Usługa nie zwróciła żadnego twierdzenia."
        return "\n\n".join([notice, *warning, *_moderator(check)])
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
        sections.insert(0, "\n".join(_page(check.page, url_limit)))
    sections[:0] = _image(check, True)
    sections += warning + [
        _claim(n, c, url_limit) for n, c in enumerate(check.claims, 1)
    ]
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
    return "\n\n".join(sections + _moderator(check))


def split(text: str) -> list[str]:
    """Cut text into Discord messages between lines.

    Every line is shorter than a message (`_field` wraps), so a cut never falls inside a line.
    """
    parts, current = [], ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > MESSAGE_LIMIT:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    return parts


def reply(check: CheckResult) -> tuple[list[str], str | None]:
    """Messages for one check, plus the full text to attach when the messages would lose any.

    At most MAX_MESSAGES messages. Nothing is dropped: whatever does not fit (more messages,
    or a URL longer than a message) is in the attachment, which holds the whole answer.
    """
    text, full = render(check), render(check, url_limit=None)
    parts = split(text)
    if len(parts) > MAX_MESSAGES:
        return [*parts[: MAX_MESSAGES - 1], ATTACHED], full
    # Fits, but a URL longer than a message was replaced: its line points to the file.
    return parts, None if text == full else full


def _notice(message: str) -> CheckResult:
    return CheckResult(status=Status.TECHNICAL_ERROR, message=message)


async def ask_api(
    text: str, client: httpx2.AsyncClient, image: str | None = None
) -> CheckResult:
    """The same request the web form sends; `image` is base64. Any failure becomes a notice,
    never a verdict."""
    body = {"input": text, **({"image": image} if image else {})}
    try:
        # httpx timeouts are per read; this caps the whole call, body included.
        async with asyncio.timeout(API_TIMEOUT_S):
            resp = await client.post(
                "/api/checks", json=body, headers={"X-Channel": CHANNEL}
            )
    except (httpx2.HTTPError, TimeoutError):
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


async def read_attachment(
    attachment: discord.Attachment,
) -> tuple[str | None, str | None]:
    """The attached image as base64 for the API, or the Polish reason it is not sent."""
    declared = (attachment.content_type or "").split(";")[0].strip()
    # No declared type: the API tells from the file itself.
    if declared and declared not in IMAGE_TYPES:
        return None, image_input.WRONG_TYPE
    if attachment.size > image_input.MAX_IMAGE_BYTES:
        return None, image_input.TOO_LARGE
    try:
        async with asyncio.timeout(DOWNLOAD_TIMEOUT_S):
            data = await attachment.read()
    # discord.py fetches the file with aiohttp and lets its network errors through.
    except (discord.HTTPException, aiohttp.ClientError, TimeoutError):
        log.exception("attachment download failed")
        return None, ATTACHMENT_UNREAD
    return base64.b64encode(data).decode(), None


async def check_command(
    text: str, attachment: discord.Attachment | None, client: httpx2.AsyncClient
) -> CheckResult:
    """What /sprawdz answers: the API's check of the text and the attached image."""
    image = None
    if attachment is not None:
        image, problem = await read_attachment(attachment)
        if problem:
            return CheckResult(status=Status.CANNOT_CHECK, message=problem)
    if not image:
        if not text:
            return CheckResult(status=Status.CANNOT_CHECK, message=NOTHING_TO_CHECK)
        return await ask_api(text, client)
    return await ask_api(text, client, image=image)


async def send(interaction: discord.Interaction, text: str, **kwargs) -> None:
    await interaction.followup.send(
        text,
        allowed_mentions=discord.AllowedMentions.none(),
        suppress_embeds=True,
        **kwargs,
    )


class Bot(discord.Client):
    def __init__(self, base_url: str) -> None:
        # Slash commands need no privileged intent (no message content).
        super().__init__(intents=discord.Intents.default())
        self.base_url = base_url
        self.api: httpx2.AsyncClient | None = None
        self.tree = app_commands.CommandTree(self)

        @self.tree.command(
            name="sprawdz", description="Sprawdź twierdzenia w tekście albo na obrazie."
        )
        @app_commands.describe(
            tekst="Tekst do sprawdzenia",
            obraz="Zrzut ekranu albo zdjęcie: PNG, JPEG lub WebP, do 5 MB",
        )
        async def sprawdz(
            interaction: discord.Interaction,
            tekst: app_commands.Range[str, 1, MAX_INPUT_CHARS] | None = None,
            obraz: discord.Attachment | None = None,
        ) -> None:
            # Acknowledge within Discord's 3 s window; the check can take up to a minute.
            await interaction.response.defer(thinking=True)
            check = await check_command(tekst or "", obraz, self.api)
            log.info(
                "check status=%s input_chars=%d image=%s",
                check.status,
                len(tekst or ""),
                obraz is not None,
            )
            parts, full = reply(check)
            last = parts.pop()
            for part in parts:
                await send(interaction, part)
            if full is None:
                await send(interaction, last)
                return
            try:
                file = discord.File(io.BytesIO(full.encode()), filename=ATTACHMENT_NAME)
                await send(interaction, last, file=file)
            except discord.HTTPException:
                log.exception("attachment refused")
                # Separate messages: `last` alone can fill Discord's 2000 characters.
                # ATTACHED points to the file that failed, so the notice replaces it and the
                # 5-message cap holds; otherwise a five-part answer gets a sixth message.
                try:
                    if last != ATTACHED:
                        await send(interaction, last)
                    await send(interaction, ATTACHMENT_FAILED)
                except discord.HTTPException:
                    log.exception("fallback message refused")

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
