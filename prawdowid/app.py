"""HTTP API. Channels (the web frontend now) call it; it calls verify and returns CheckResult."""

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from cachetools import TTLCache
from fastapi import FastAPI, Header, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from pydantic_core import PydanticCustomError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from prawdowid import checklog, corpus_bm25, faults
from prawdowid.contract import CheckResult, Status, Verdict
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
# Channels send X-Channel; logged so checks can be compared across channels. "demo" is the
# messenger demo adapter at /czat (frontend/public/czat.js).
CHANNELS = {"web", "discord", "demo"}
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

API_DESCRIPTION = (
    "Fact-checks a message or a link in Polish. Each checkable claim gets a verdict "
    "with the sources behind it: a quote, the publisher, the date and a link. When "
    "the evidence is not there, the verdict says so.\n\n"
    "The web page and the Discord bot call `POST /api/checks`. A new channel does the "
    f"same and names itself in `X-Channel`. The limit is {RATE_LIMIT} per client IP."
)
CHECK_DESCRIPTION = (
    "`input` is a message, a question or one `http`/`https` link. For a link the "
    f"server fetches the page and checks its text. Allow up to {VERIFY_TIMEOUT_S} s "
    "for the answer.\n\n"
    "A check that could not run still returns `200`: `status` is then "
    "`technical_error`, `cannot_check` or `needs_clarification`, and `message` says "
    "why in Polish. An `input` that is empty, too long or not a valid link returns "
    "`422` with a Polish text in `detail[0].msg`; too many requests return `429`."
)

_http_url = TypeAdapter(HttpUrl)

# Same text, same answer: a channel (web, Discord) asking again within the TTL gets the stored
# result instead of a second model run that could split the claims differently. In process, so
# a restart or a second worker starts empty; never shared and never persisted.
RESULT_CACHE_TTL_S = 30 * 60
RESULT_CACHE_SIZE = 500
_results: TTLCache[str, CheckResult] = TTLCache(
    maxsize=RESULT_CACHE_SIZE, ttl=RESULT_CACHE_TTL_S
)


def cache_key(text: str) -> str:
    """Hash of the input with whitespace collapsed (CheckRequest already made it NFC), so the raw
    text is not kept as a key. Session and channel stay out of it."""
    normalised = " ".join(unicodedata.normalize("NFC", text).split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _cacheable(result: CheckResult) -> bool:
    """Only a finished check: not an error, and no claim left unchecked by a source failure."""
    return result.status != Status.TECHNICAL_ERROR and not any(
        c.verdict == Verdict.NOT_CHECKED for c in result.claims
    )


class CheckRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "input": "Czy w aplikacji Odyseusz można zarejestrować wyjazd za granicę?"
                }
            ]
        }
    )

    input: str = Field(
        description=(
            f"1 to {MAX_INPUT_CHARS} characters after trimming. A single token with "
            "`://` is read as a link and must be a valid http or https URL."
        )
    )

    @field_validator("input")
    @classmethod
    def _valid_input(cls, value: str) -> str:
        # NFC, so the pipeline sees what the cache key hashes (a decomposed ń must not slip past
        # the injection patterns, which are written with composed letters).
        value = unicodedata.normalize("NFC", value).strip()
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The corpus index takes about a second to build: do it now, not inside the first check. No
    # queries builds it and searches nothing. A failure is only logged: the first lookup retries.
    try:
        await corpus_bm25.search_evidence([])
    except Exception:
        log.exception("corpus warm-up failed")
    yield


class RateLimitError(BaseModel):
    detail: str = Field(examples=[RATE_LIMIT_MESSAGE])


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="PRAWDOWID",
    description=API_DESCRIPTION,
    lifespan=lifespan,
    # Under /api/, the only prefix besides /health that the public site forwards.
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    # One docs page; no ReDoc and no OAuth2 redirect route (the API has no OAuth).
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=None,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": RATE_LIMIT_MESSAGE}, status_code=429)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/checks",
    summary="Check a text or a link",
    description=CHECK_DESCRIPTION,
    responses={
        200: {
            "description": "The check result; `status` says whether the check ran.",
            "headers": {
                SESSION_HEADER: {
                    "description": "The session of this check: the one sent, or a "
                    "new one. Send it back on the next check.",
                    "schema": {"type": "string"},
                }
            },
        },
        429: {"description": "Rate limit reached.", "model": RateLimitError},
    },
)
@limiter.limit(RATE_LIMIT)
async def create_check(
    request: Request,
    response: Response,
    body: CheckRequest,
    x_channel: Annotated[
        str,
        Header(
            alias="X-Channel",
            description=(
                "The calling channel, logged with every check. Known values: "
                f"{', '.join(sorted(CHANNELS))}. Any other value is logged as `other`."
            ),
        ),
    ] = "web",
    x_session_id: Annotated[
        str | None,
        Header(
            alias=SESSION_HEADER,
            description=(
                "Session id from an earlier answer: 8 to 64 letters, digits or "
                "hyphens. The session's checks are kept together, and "
                "`DELETE /api/sessions/{session}` removes them. Without a valid id "
                "the server starts a new session."
            ),
        ),
    ] = None,
) -> CheckResult:
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    session = x_session_id or ""
    if not re.fullmatch(SESSION_ID, session):
        session = str(uuid.uuid4())
    response.headers[SESSION_HEADER] = session
    # Why a check ended in a technical error, for the check log; None when verify returned.
    error = None
    key = cache_key(body.input)
    # Eval traffic only (scenario J): honoured with the secret eval token, ignored for everyone
    # else. A faulted run neither reads nor fills the result cache: a stored answer would hide
    # the simulated outage, and an answer computed with a dependency "down" is not the real one.
    fault = faults.requested(request.headers)
    cached = None if fault else _results.get(key)
    try:
        if cached:
            result = cached.model_copy(deep=True)
            # Lets a client (the eval) tell a stored answer from a fresh run, e.g. for latency.
            response.headers["X-Cache"] = "hit"
        else:
            with faults.simulate(fault):
                async with asyncio.timeout(VERIFY_TIMEOUT_S):
                    result = await verify(body.input)
            if not fault and _cacheable(result):
                _results[key] = result.model_copy(deep=True)
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
    # Scenario I context, added after the verdicts so it cannot change them.
    try:
        # The final address after redirects counts too (a short link to a known page).
        final_url = result.page.url if result.page else ""
        result.incident_matches = match_incidents(f"{body.input} {final_url}")
    except Exception:
        log.exception("incident matching failed")
    channel = x_channel if x_channel in CHANNELS else "other"
    latency_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        "check session=%s channel=%s status=%s security_events=%d cost_usd=%s cache=%s "
        "latency_ms=%d input_chars=%d",
        session,
        channel,
        result.status,
        len(result.security_events),
        0.0 if cached else result.cost_usd,
        "hit" if cached else "miss",
        latency_ms,
        len(body.input),
    )
    # A hit cost nothing and ran no steps: the check log must not count them twice.
    logged = result
    if cached:
        logged = result.model_copy(
            update={
                "cost_usd": 0.0,
                "steps_ms": {},
                "model_calls": [],
                "claims": [
                    c.model_copy(update={"steps_ms": {}}) for c in result.claims
                ],
            }
        )
    checklog.record(
        session,
        channel,
        body.input,
        logged,
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
    """Delete every check record of a demo session (the check log is all a check stores)."""
    deleted = checklog.delete_session(session)
    log.info("session deleted session=%s records=%d", session, deleted)
    return {"deleted": deleted}
