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
)
from pydantic_core import PydanticCustomError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from prawdowid import cases, checklog, corpus_bm25, export, faults
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
    """Hash of the input (CheckRequest already made it NFC), so the raw text is not kept as a key.
    Internal whitespace stays: the model reads it and it can change the verdict. Session and
    channel stay out of it."""
    normalised = unicodedata.normalize("NFC", text)
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
    # Scenario I context, added after the verdicts so it cannot change them.
    try:
        # The final address after redirects counts too (a short link to a known page).
        final_url = result.page.url if result.page else ""
        result.incident_matches = match_incidents(f"{body.input} {final_url}")
    except Exception:
        log.exception("incident matching failed")
    channel = x_channel if x_channel in CHANNELS else "other"
    # Scenario H: set only once the case is stored, and never while nobody can read the queue
    # (PRAWDOWID_ADMIN_TOKEN unset), so an answer never claims a hand-off that did not happen.
    # A hit is one more question: it counts.
    result.moderator_case = cases.report(
        session, channel, body.input, result, started_at=started_at
    )
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
    token = cases.admin_token()
    if not token:
        raise HTTPException(status_code=404)
    given = credentials.credentials if credentials else ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        log.warning("moderator cases refused: wrong or missing token")
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return cases.read_cases()


def _require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin)],
) -> None:
    """Same token and answers as `/api/cases`: 404 without PRAWDOWID_ADMIN_TOKEN, 401 on a wrong one."""
    token = cases.admin_token()
    if not token:
        raise HTTPException(status_code=404)
    given = credentials.credentials if credentials else ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        log.warning("admin export refused: wrong or missing token")
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
        bundle = export.stix_bundle(CheckResult.model_validate_json(body))
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


@app.get(
    "/api/export/checks",
    include_in_schema=False,
    dependencies=[Depends(_require_admin)],
)
@limiter.limit(RATE_LIMIT)
def export_checks(
    request: Request,
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "json",
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> Response:
    """The masked check log for a date range (UTC days, default: the retention period) as CSV or
    JSON, for the holder of PRAWDOWID_ADMIN_TOKEN. No session ids. Not in the channel spec."""
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
