"""HTTP API. Channels (the web frontend now) call it; it calls verify and returns CheckResult."""

import asyncio
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, TypeAdapter, ValidationError, field_validator
from pydantic_core import PydanticCustomError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from prawdowid.contract import CheckResult, Status
from prawdowid.verifier import failed, is_link, verify

logging.basicConfig(level=logging.INFO, format="%(levelname)s:  %(name)s %(message)s")
log = logging.getLogger("prawdowid")

MAX_INPUT_CHARS = 5000
RATE_LIMIT = "10/minute"
VERIFY_TIMEOUT_S = 60
# Channels send X-Channel; logged so checks can be compared across channels.
CHANNELS = {"web", "discord"}
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
async def create_check(request: Request, body: CheckRequest) -> CheckResult:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT_S):
            result = await verify(body.input)
    except Exception:
        log.exception("verify failed")
        # Cost unknown: a model request may have been sent before the failure.
        result = failed(
            body.input, Status.TECHNICAL_ERROR, TECHNICAL_ERROR_MESSAGE, cost=None
        )
        if is_link(body.input):
            # Only the URL was screened, not the page, so the "patterns only" note would mislead.
            result.limitations = []
    # ponytail: stdout log instead of a check store until the team picks storage.
    channel = request.headers.get("x-channel", "web")
    log.info(
        "check channel=%s status=%s security_events=%d cost_usd=%s latency_ms=%d input_chars=%d",
        channel if channel in CHANNELS else "other",
        result.status,
        len(result.security_events),
        result.cost_usd,
        round((time.perf_counter() - started) * 1000),
        len(body.input),
    )
    return result
