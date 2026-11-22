"""HTTP API. Channels (the web frontend now) call it; it calls verify and returns CheckResult."""

import asyncio
import hashlib
import hmac
import logging
import re
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated

from cachetools import TTLCache
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool

from prawdowid import cases, checklog, corpus_bm25, export, faults, image_input
from prawdowid.contract import CheckResult, Status, Verdict
from prawdowid.incidents import match_incidents
from prawdowid.privacy import MaskingFilter
from prawdowid.sources import SourceList, source_list
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
    "`422` with a Polish text in `detail[0].msg`; too many requests return `429`.\n\n"
    "`image` is an optional screenshot or photo in base64: a PNG, JPEG or WebP of at "
    f"most {image_input.MAX_IMAGE_BYTES // (1024 * 1024)} MB, "
    f"{image_input.MAX_IMAGE_PIXELS // 1_000_000} million pixels and "
    f"{image_input.MAX_IMAGE_SIDE} px a side. A model reads its text and any visible "
    "date, and that text is checked like `input`, which may then be empty and is "
    "checked along with it. The answer's `image` shows the text that was read and "
    "`limitations` what an image check cannot tell. The image goes to the model "
    "provider as uploaded, metadata included; the API does not store it. Another "
    "type, a larger image or an image with a link returns `422`."
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


def cache_key(text: str, image_sha256: str | None = None) -> str:
    """Hash of the input (CheckRequest already made it NFC), so the raw text is not kept as a key.
    Internal whitespace stays: the model reads it and it can change the verdict. An image counts
    by its hash, so the same words with another image are another check. Session and channel
    stay out of it."""
    normalised = unicodedata.normalize("NFC", text)
    if image_sha256:
        normalised += f"\0image:{image_sha256}"
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
        "",
        description=(
            f"1 to {MAX_INPUT_CHARS} characters after trimming; may be empty only with "
            "`image`. A single token with `://` is read as a link and must be a valid "
            "http or https URL."
        ),
    )
    image: str | None = Field(
        None,
        description=(
            "Optional screenshot or photo: base64 of a PNG, JPEG or WebP file (a data URL "
            f"is accepted too), at most {image_input.MAX_IMAGE_BYTES // (1024 * 1024)} MB, "
            f"{image_input.MAX_IMAGE_PIXELS // 1_000_000} million pixels and "
            f"{image_input.MAX_IMAGE_SIDE} px a side. Sent to the model provider as "
            "uploaded; the API never stores it."
        ),
    )

    @field_validator("input")
    @classmethod
    def _valid_input(cls, value: str) -> str:
        # NFC, so the pipeline sees what the cache key hashes (a decomposed ń must not slip past
        # the injection patterns, which are written with composed letters).
        value = unicodedata.normalize("NFC", value).strip()
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

    @model_validator(mode="after")
    def _text_or_image(self) -> "CheckRequest":
        # The image itself is decoded in create_check, after the rate limit counted the request.
        if not self.image:
            if not self.input:
                raise PydanticCustomError("empty", "Wpisz tekst do sprawdzenia.")
        elif is_link(self.input):
            raise PydanticCustomError("link_and_image", image_input.LINK_AND_IMAGE)
        return self


def decoded_image(body: CheckRequest) -> image_input.Upload | None:
    """The request's image, checked. Called inside the endpoint, so a refused image counts
    against the rate limit (validation runs before it); each failure is the same Polish 422 as a
    validation error, without the input."""
    if not body.image:
        return None
    try:
        # Type, size and pixel count come from the file itself.
        return image_input.decode(body.image)
    except PydanticCustomError as exc:
        error = {"type": exc.type, "loc": ("body", "image"), "msg": exc.message()}
        raise RequestValidationError([error]) from None


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


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    """FastAPI's 422 without the echo of the input: a refused image would come back whole."""
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)


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
    upload = decoded_image(body)
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    session = x_session_id or ""
    if not re.fullmatch(SESSION_ID, session):
        session = str(uuid.uuid4())
    response.headers[SESSION_HEADER] = session
    # Why a check ended in a technical error, for the check log; None when verify returned.
    error = None
    key = cache_key(body.input, upload and upload.sha256)
    # Eval traffic only (scenario J): honoured with the secret eval token, ignored for everyone
    # else. A faulted run neither reads nor fills the result cache: a stored answer would hide
    # the simulated outage, and an answer computed with a dependency "down" is not the real one.
    fault = faults.requested(request.headers)
    if fault:
        # Tells the eval the fault was applied (see faults.APPLIED_HEADER); absent for everyone else.
        response.headers[faults.APPLIED_HEADER] = fault
    cached = None if fault else _results.get(key)
    try:
        if cached:
            result = cached.model_copy(deep=True)
            # Lets a client (the eval) tell a stored answer from a fresh run, e.g. for latency.
            response.headers["X-Cache"] = "hit"
        else:
            with faults.simulate(fault):
                async with asyncio.timeout(VERIFY_TIMEOUT_S):
                    if upload:
                        result = await image_input.verify_image(upload, body.input)
                    else:
                        result = await verify(body.input)
            if not fault and _cacheable(result):
                _results[key] = result.model_copy(deep=True)
    except Exception as exc:
        log.exception("verify failed")
        error = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        # A model request may have been sent before the failure: counted as unpriced.
        result = failed(
            body.input, Status.TECHNICAL_ERROR, TECHNICAL_ERROR_MESSAGE, unpriced=1
        )
        if is_link(body.input):
            # Only the URL was screened, not the page, so the "patterns only" note would mislead.
            result.limitations = []
        if upload:
            # Likewise only the typed text, not the image; its hash still goes to the check log.
            result.limitations = list(image_input.UNREAD)
            result.image = image_input.received(upload)
    # Text read from an image (masked), or "".
    read = (result.image and result.image.text) or ""
    # Scenario I context, added after the verdicts so it cannot change them.
    try:
        # The final address after redirects counts too (a short link to a known page).
        final_url = result.page.url if result.page else ""
        result.incident_matches = match_incidents(f"{body.input} {final_url} {read}")
    except Exception:
        log.exception("incident matching failed")
    channel = x_channel if x_channel in CHANNELS else "other"
    # Scenario H: set only once the case is stored, and never while nobody can read the queue
    # (PRAWDOWID_ADMIN_TOKEN unset), so an answer never claims a hand-off that did not happen.
    # A hit is one more question: it counts.
    # An image sent alone: the moderator sees the text read from it (masked).
    result.moderator_case = cases.report(
        session, channel, body.input or read, result, started_at=started_at
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        "check session=%s channel=%s status=%s security_events=%d cost_usd=%s cache=%s "
        "latency_ms=%d input_chars=%d image=%s",
        session,
        channel,
        result.status,
        len(result.security_events),
        0.0 if cached else result.cost_usd,
        "hit" if cached else "miss",
        latency_ms,
        len(body.input),
        upload.sha256 if upload else "-",
    )
    # A hit cost nothing and ran no steps: the check log must not count them twice.
    logged = result
    if cached:
        logged = result.model_copy(
            update={
                "cost_usd": 0.0,
                "unpriced_requests": 0,
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
    """Delete every check record of a demo session (`deleted`), and take its questions out of
    the moderator cases (`withdrawn`)."""
    deleted = checklog.delete_session(session)
    withdrawn = cases.delete_session(session)
    log.info(
        "session deleted session=%s records=%d withdrawn=%d",
        session,
        deleted,
        withdrawn,
    )
    return {"deleted": deleted, "withdrawn": withdrawn}


@app.get("/api/sources")
def list_sources() -> SourceList:
    """Every source a check uses, for the page /zrodla. Plain def: the first call reads the
    corpus file, so it runs in FastAPI's thread pool instead of blocking the event loop."""
    return source_list()


# auto_error off: without the token the route answers 404, whatever the request carries.
_admin = HTTPBearer(auto_error=False)


@app.get("/api/cases", include_in_schema=False)
@limiter.limit(RATE_LIMIT)
def list_cases(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin)],
) -> list[cases.CaseSummary]:
    """The moderator's queue (prawdowid/cases.py) for whoever holds the bearer token set in
    PRAWDOWID_ADMIN_TOKEN; without the variable there is no queue (no check files a case) and the
    route does not exist. Left out of the channel spec (docs/openapi.json): no channel calls it.
    Plain def: it reads a file."""
    _check_admin(credentials)
    return cases.read_cases()


def _check_admin(credentials: HTTPAuthorizationCredentials | None) -> None:
    """404 without PRAWDOWID_ADMIN_TOKEN, 401 on a missing or wrong bearer token. Call it inside
    the rate-limited route body: slowapi counts only when the endpoint runs, not in a dependency,
    so a check made as a dependency would leave wrong guesses unlimited."""
    token = cases.admin_token()
    if not token:
        raise HTTPException(status_code=404)
    given = credentials.credentials if credentials else ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        log.warning("admin route refused: wrong or missing token")
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})


@app.post("/api/export/stix")
@limiter.limit(RATE_LIMIT)
async def export_stix(request: Request) -> Response:
    """The answer the client holds (the JSON of `POST /api/checks`) as a STIX 2.1 bundle
    (prawdowid/export.py). Masked again, nothing fetched; at most `export.MAX_ANSWER_BYTES` read."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > export.MAX_ANSWER_BYTES:
            raise HTTPException(
                status_code=413, detail="Odpowiedź jest za duża do eksportu."
            )
    try:
        answer = CheckResult.model_validate_json(body)
        # A thread: building the bundle is CPU work and must not stall the event loop.
        bundle = await run_in_threadpool(export.stix_bundle, answer)
    except (ValidationError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="To nie jest odpowiedź z wynikami do wyeksportowania.",
        ) from None
    return Response(
        bundle,
        media_type="application/stix+json;version=2.1",
        headers={"Content-Disposition": 'attachment; filename="faktczyfejk-stix.json"'},
    )


DATE_MIN, DATE_MAX = (
    date(2020, 1, 1),
    date(2100, 1, 1),
)  # keeps `to` + 1 day inside datetime


@app.get("/api/export/checks", include_in_schema=False)
@limiter.limit(RATE_LIMIT)
def export_checks(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin)],
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "json",
    start: Annotated[date | None, Query(alias="from", ge=DATE_MIN, le=DATE_MAX)] = None,
    end: Annotated[date | None, Query(alias="to", ge=DATE_MIN, le=DATE_MAX)] = None,
) -> Response:
    """The masked check log for a date range (UTC days, default: the retention period) as CSV or
    JSON, for the holder of PRAWDOWID_ADMIN_TOKEN. No session ids. Not in the channel spec."""
    _check_admin(credentials)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="`from` is after `to`.")
    records = export.log_records(start, end)
    if format == "csv":
        return PlainTextResponse(
            export.log_csv(records),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="checks.csv"'},
        )
    return JSONResponse(
        records, headers={"Content-Disposition": 'attachment; filename="checks.json"'}
    )
