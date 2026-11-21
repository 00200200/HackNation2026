"""HTTP API. Channels (the web frontend now) call it; it calls verify and returns CheckResult."""

import asyncio
import logging
import re
import time
import uuid

from fastapi import FastAPI, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, TypeAdapter, ValidationError, field_validator
from pydantic_core import PydanticCustomError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from prawdowid import checklog
from prawdowid.contract import CheckResult, Status
from prawdowid.incidents import match_incidents
from prawdowid.verifier import is_link, verify

logging.basicConfig(level=logging.INFO, format="%(levelname)s:  %(name)s %(message)s")
log = logging.getLogger("prawdowid")

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
    session = request.headers.get(SESSION_HEADER, "")
    if not re.fullmatch(SESSION_ID, session):
        session = str(uuid.uuid4())
    response.headers[SESSION_HEADER] = session
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT_S):
            result = await verify(body.input)
    except Exception:
        log.exception("verify failed")
        result = CheckResult(
            status=Status.TECHNICAL_ERROR, message=TECHNICAL_ERROR_MESSAGE
        )
    # Scenario I context, added after the verdicts so it cannot change them.
    try:
        # The final address after redirects counts too (a short link to a known page).
        final_url = result.page.url if result.page else ""
        result.incident_matches = match_incidents(f"{body.input} {final_url}")
    except Exception:
        log.exception("incident matching failed")
    channel = request.headers.get("x-channel", "web")
    channel = channel if channel in CHANNELS else "other"
    log.info(
        "check session=%s channel=%s status=%s latency_ms=%d input_chars=%d",
        session,
        channel,
        result.status,
        round((time.perf_counter() - started) * 1000),
        len(body.input),
    )
    checklog.record(session, channel, body.input, result)
    return result


@app.delete("/api/sessions/{session}")
@limiter.limit(RATE_LIMIT)
async def delete_session(
    request: Request, session: str = Path(pattern=f"^{SESSION_ID}$")
) -> dict:
    """Delete every check record of a demo session (the check log is all a check stores)."""
    deleted = checklog.delete_session(session)
    log.info("session deleted session=%s records=%d", session, deleted)
    return {"deleted": deleted}
