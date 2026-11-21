"""HTTP API and the web channel. Channels only translate input and render CheckResult."""

import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import (
    BaseModel,
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

from prawdowid import checklog
from prawdowid.contract import CheckResult, Status
from prawdowid.verifier import verify

log = logging.getLogger("prawdowid")

MAX_INPUT_CHARS = 5000
RATE_LIMIT = "10/minute"
VERIFY_TIMEOUT_S = 60
SESSION_COOKIE = "prawdowid_session"
TECHNICAL_ERROR_MESSAGE = "Wystąpił błąd techniczny i nie udało się sprawdzić tej treści. Spróbuj ponownie za chwilę."
RATE_LIMIT_MESSAGE = (
    "Wysłano za dużo zapytań w krótkim czasie. Odczekaj minutę i spróbuj ponownie."
)

_http_url = TypeAdapter(HttpUrl)


class CheckRequest(BaseModel):
    input: str
    session_id: str | None = Field(default=None, max_length=100)

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
                    "To nie wygląda na poprawny link. Przyjmujemy adresy zaczynające się od http:// lub https://.",
                ) from None
        return value


class CheckResponse(BaseModel):
    id: str
    result: CheckResult


async def run_check(req: CheckRequest, channel: str) -> CheckResponse:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT_S):
            result = await verify(req.input)
    except Exception:
        log.exception("verify failed")
        result = CheckResult(
            status=Status.TECHNICAL_ERROR, message=TECHNICAL_ERROR_MESSAGE
        )
    latency_ms = round((time.perf_counter() - started) * 1000)
    check_id = checklog.add(
        session_id=req.session_id,
        channel=channel,
        input=req.input,
        result=result,
        latency_ms=latency_ms,
    )
    return CheckResponse(id=check_id, result=result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    checklog.init()
    yield


limiter = Limiter(key_func=get_remote_address)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app = FastAPI(title="PRAWDOWID", lifespan=lifespan)
app.state.limiter = limiter


def web_session(request: Request) -> str:
    """Session id of this browser: its cookie if well-formed, else a new one for this request."""
    if not hasattr(request.state, "session_id"):
        cookie = request.cookies.get(SESSION_COOKIE, "")
        valid = re.fullmatch(r"[0-9a-f]{32}", cookie)
        request.state.session_id = cookie if valid else uuid.uuid4().hex
    return request.state.session_id


def render_page(request: Request, status_code: int = 200, **context) -> HTMLResponse:
    session_id = web_session(request)
    response = templates.TemplateResponse(
        request,
        "index.html",
        {"max_chars": MAX_INPUT_CHARS, "session_id": session_id, **context},
        status_code=status_code,
    )
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax")
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": RATE_LIMIT_MESSAGE}, status_code=429)
    return render_page(request, 429, error=RATE_LIMIT_MESSAGE)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/checks")
@limiter.limit(RATE_LIMIT)
async def create_check(request: Request, body: CheckRequest) -> CheckResponse:
    return await run_check(body, channel="api")


@app.get("/api/checks")
async def list_checks() -> list[dict]:
    return checklog.list_all()


@app.get("/api/checks/{check_id}")
async def get_check(check_id: str) -> dict:
    record = checklog.get(check_id)
    if record is None:
        raise HTTPException(404, "Nie znaleziono takiego sprawdzenia.")
    return record


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    return {"deleted": checklog.delete_session(session_id)}


@app.get("/", response_class=HTMLResponse)
async def page(request: Request):
    return render_page(request)


@app.post("/", response_class=HTMLResponse)
@limiter.limit(RATE_LIMIT)
async def page_submit(request: Request, input: Annotated[str, Form()] = ""):
    try:
        req = CheckRequest(input=input, session_id=web_session(request))
    except ValidationError as e:
        return render_page(request, 422, error=e.errors()[0]["msg"], input=input)
    check = await run_check(req, channel="web")
    return render_page(request, check=check, input=req.input)
