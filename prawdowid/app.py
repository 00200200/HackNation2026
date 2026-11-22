"""HTTP API. Channels (the web frontend now) call it; it calls verify and returns CheckResult."""

import asyncio
import hmac
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from pydantic_core import PydanticCustomError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from prawdowid import checklog, faults, moderation
from prawdowid.contract import CheckResult, ModeratorAnswer, Status, Verdict
from prawdowid.incidents import match_incidents
from prawdowid.privacy import MaskingFilter
from prawdowid.verifier import failed, is_link, verify

logging.basicConfig(level=logging.INFO, format="%(levelname)s:  %(name)s %(message)s")
log = logging.getLogger("prawdowid")
# Last line of defence: an unexpected exception (logged with its traceback) can carry raw input.
log.addFilter(MaskingFilter())

MAX_INPUT_CHARS = 5000
RATE_LIMIT = "10/minute"
VERIFY_TIMEOUT_S = 60
# Channels send X-Channel; logged so checks can be compared across channels.
CHANNELS = {"web", "discord"}
# Demo session: the client sends X-Session-Id back on later checks; a new one is issued otherwise.
SESSION_HEADER = "X-Session-Id"
SESSION_ID = r"[A-Za-z0-9-]{8,64}"
TECHNICAL_ERROR_MESSAGE = (
    "Wystąpił błąd techniczny i nie udało się sprawdzić tej treści. "
    "Spróbuj ponownie za chwilę."
)
# The moderator panel is off (404) unless the server has a token; the panel sends it as a Bearer.
MODERATOR_TOKEN = os.getenv("PRAWDOWID_MODERATOR_TOKEN") or ""
CASE_ID = r"[0-9A-F]{16}"
BEARER = HTTPBearer(auto_error=False)
Auth = Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)]
RATE_LIMIT_MESSAGE = (
    "Wysłano za dużo zapytań w krótkim czasie. Odczekaj minutę i spróbuj ponownie."
)

_http_url = TypeAdapter(HttpUrl)


class CheckRequest(BaseModel):
    input: str

    @field_validator("input")
    @classmethod
    def _valid_input(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise PydanticCustomError("empty", "Wpisz tekst do sprawdzenia.")
        if len(value) > MAX_INPUT_CHARS:
            raise PydanticCustomError(
                "too_long", f"Treść jest za długa. Limit to {MAX_INPUT_CHARS} znaków."
            )
        if is_link(value):
            try:
                _http_url.validate_python(value)
            except ValidationError:
                raise PydanticCustomError(
                    "bad_url",
                    "To nie wygląda na poprawny link. "
                    "Przyjmujemy adresy zaczynające się od http:// lub https://.",
                ) from None
        return value


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="PRAWDOWID")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": RATE_LIMIT_MESSAGE}, status_code=429)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/checks")
@limiter.limit(RATE_LIMIT)
async def create_check(
    request: Request, response: Response, body: CheckRequest
) -> CheckResult:
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    session = request.headers.get(SESSION_HEADER, "")
    if not re.fullmatch(SESSION_ID, session):
        session = str(uuid.uuid4())
    response.headers[SESSION_HEADER] = session
    # Why a check ended in a technical error, for the check log; None when verify returned.
    error = None
    fault = faults.active.set(faults.requested(request.headers.get(faults.HEADER)))
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT_S):
            result = await verify(body.input)
    except Exception as exc:
        log.exception("verify failed")
        error = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        # Cost unknown: a model request may have been sent before the failure.
        result = failed(
            body.input, Status.TECHNICAL_ERROR, TECHNICAL_ERROR_MESSAGE, cost=None
        )
        if is_link(body.input):
            # Only the URL was screened, not the page, so the "patterns only" note would mislead.
            result.limitations = []
    finally:
        faults.active.reset(fault)
    # Scenario I context, added after the verdicts so it cannot change them.
    try:
        # The final address after redirects counts too (a short link to a known page).
        final_url = result.page.url if result.page else ""
        result.incident_matches = match_incidents(f"{body.input} {final_url}")
    except Exception:
        log.exception("incident matching failed")
    try:
        await asyncio.to_thread(_moderate, body.input, result)
    except Exception:
        log.exception("moderator case failed")
    channel = request.headers.get("x-channel", "web")
    channel = channel if channel in CHANNELS else "other"
    latency_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        "check session=%s channel=%s status=%s security_events=%d cost_usd=%s latency_ms=%d input_chars=%d",
        session,
        channel,
        result.status,
        len(result.security_events),
        result.cost_usd,
        latency_ms,
        len(body.input),
    )
    checklog.record(
        session,
        channel,
        body.input,
        result,
        started_at=started_at,
        latency_ms=latency_ms,
        error=error,
    )
    return result


@app.get("/api/sessions/{session}")
@limiter.limit(RATE_LIMIT)
async def read_session(
    request: Request, session: str = Path(pattern=f"^{SESSION_ID}$")
) -> list[dict]:
    """Every check record of a demo session, oldest first, as stored (masked)."""
    return checklog.read_session(session)


@app.delete("/api/sessions/{session}")
@limiter.limit(RATE_LIMIT)
async def delete_session(
    request: Request, session: str = Path(pattern=f"^{SESSION_ID}$")
) -> dict:
    """Delete every check record of a demo session. Moderator cases carry no session and stay
    (docs/privacy.md)."""
    deleted = checklog.delete_session(session)
    log.info("session deleted session=%s records=%d", session, deleted)
    return {"deleted": deleted}


def _moderator(auth: Auth) -> None:
    """404 while the panel is off, 401 without the right token. A route dependency, so it runs
    before the body is validated."""
    if not MODERATOR_TOKEN:
        raise HTTPException(404, "Panel moderatora jest wyłączony.")
    given = auth.credentials if auth else ""
    if not hmac.compare_digest(given.encode(), MODERATOR_TOKEN.encode()):
        raise HTTPException(401, "Nieprawidłowy token.")


class AnswerRequest(BaseModel):
    answer: str

    @field_validator("answer")
    @classmethod
    def _valid_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise PydanticCustomError("empty", "Wpisz odpowiedź.")
        if len(value) > moderation.MAX_ANSWER_CHARS:
            raise PydanticCustomError(
                "too_long",
                f"Odpowiedź jest za długa. Limit to {moderation.MAX_ANSWER_CHARS} znaków.",
            )
        return value


@app.get("/api/moderator/cases", dependencies=[Depends(_moderator)])
@limiter.limit(RATE_LIMIT)
async def moderator_cases(request: Request) -> list[moderation.Case]:
    return await asyncio.to_thread(moderation.list_cases)


@app.post("/api/moderator/cases/{case}/answer", dependencies=[Depends(_moderator)])
@limiter.limit(RATE_LIMIT)
async def moderator_answer(
    request: Request, body: AnswerRequest, case: str = Path(pattern=f"^{CASE_ID}$")
) -> moderation.Case:
    answered = await asyncio.to_thread(moderation.answer, case, body.answer)
    if answered is None:
        raise HTTPException(404, "Nie ma takiej sprawy.")
    log.info("moderator answered case=%s", case)
    return answered


def _moderate(question: str, result: CheckResult) -> None:
    """Scenario H: the main claim without evidence opens (or counts) the question's case, and a
    moderator's answer to it is shown next to the result."""
    main = result.claims[0] if result.claims else None
    # With the panel off nobody can answer, so no case and no "passed to a moderator" note.
    if not MODERATOR_TOKEN or result.status is not Status.OK or not main:
        return
    if main.verdict is not Verdict.INSUFFICIENT_EVIDENCE:
        return
    case = moderation.open_case(question)
    result.moderator_case_id = case.id
    if case.answer:
        result.moderator_answer = ModeratorAnswer(
            text=case.answer, answered_at=case.answered_at
        )
