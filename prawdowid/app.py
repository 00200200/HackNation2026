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
from prawdowid.verifier import verify

logging.basicConfig(level=logging.INFO, format="%(levelname)s:  %(name)s %(message)s")
log = logging.getLogger("prawdowid")

MAX_INPUT_CHARS = 5000
RATE_LIMIT = "10/minute"
VERIFY_TIMEOUT_S = 60
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
            raise PydanticCustomError("empty", "Wpisz tekst albo wklej link.")
        if len(value) > MAX_INPUT_CHARS:
            raise PydanticCustomError(
                "too_long", f"Treść jest za długa. Limit to {MAX_INPUT_CHARS} znaków."
            )
        if "://" in value and not any(c.isspace() for c in value):
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
        result = CheckResult(
            status=Status.TECHNICAL_ERROR, message=TECHNICAL_ERROR_MESSAGE
        )
    # ponytail: stdout log instead of a check store until the team picks storage.
    log.info(
        "check status=%s latency_ms=%d input_chars=%d",
        result.status,
        round((time.perf_counter() - started) * 1000),
        len(body.input),
    )
    return result
