"""Calls the product under test and maps its answer to the eval's internal shape.

Product API: POST /api/checks with {"input": "..."} (and "image", base64, for scenario F), returns
CheckResult (prawdowid/contract.py).
Notes on the contract and its gaps: .claude/skills/prawdowid-eval/SKILL.md.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import httpx2

from prawdowid.discord_bot import ask_api
from prawdowid.faults import APPLIED_HEADER

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_S = float(os.environ.get("PRAWDOWID_TIMEOUT_S", "90"))
# The API allows 10 requests per minute per client; stay under it.
MIN_INTERVAL_S = float(os.environ.get("PRAWDOWID_MIN_INTERVAL_S", "6.5"))
# Channels besides the web API, comma-separated. "discord" runs the bot's own API client
# (prawdowid/discord_bot.ask_api), so only the Discord connection itself is not exercised.
# "demo" sends the request of the /czat demo adapter (frontend/public/czat.js): the web
# request with X-Channel: demo.
CHANNELS = {
    "web",
    *filter(None, os.environ.get("PRAWDOWID_EXTRA_CHANNELS", "").split(",")),
}
VERDICT_LABELS = {
    "confirmed": "potwierdzone",
    "false": "fałszywe",
    "misleading": "wprowadzające w błąd",
    "insufficient_evidence": "brak wystarczających dowodów",
    "not_verifiable": "nie podlega weryfikacji",
}
PASSTHROUGH = (
    "message",
    "security_events",
    "limitations",
    "cost_usd",
    "unpriced_requests",
    "moderator_case",
    "incident_matches",
    "page",
    # Scenario F: the text read from the image, kept for a reader of the results (not scored).
    "image",
)


class FaultNotApplied(RuntimeError):
    """A fault case whose simulated fault the product did not confirm. The answer is a healthy
    run, so scoring it would blame the product for a harness or deployment gap."""

    retryable = False  # set when the answer was a 429 or 5xx: one more try may reach the product


_last_call = 0.0
_turn = threading.Lock()  # concurrent cases still start one by one


def supports(channel: str) -> bool:
    return channel in CHANNELS


def wait_turn() -> None:
    """Sleep so that consecutive requests respect the API rate limit."""
    global _last_call
    with _turn:
        delay = _last_call + MIN_INTERVAL_S - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _last_call = time.monotonic()


def to_eval_shape(raw: dict) -> dict:
    claims = [
        {
            "text": c.get("claim", ""),
            # Model-written text shown in the UI, so the canary check must see it.
            "source_sentence": c.get("source_sentence", ""),
            "reasoning": c.get("reasoning", ""),
            # Model-written too (missing context in premises), so the canary check must see it.
            "premises": c.get("premises") or [],
            "limitations": c.get("limitations") or [],
            "verdict": c.get("verdict_label")
            or VERDICT_LABELS.get(c.get("verdict"), c.get("verdict", "")),
            "evidence": [
                {
                    "title": s.get("title"),
                    "publisher": s.get("publisher"),
                    "published_at": s.get("published_at"),
                    "url": s.get("url"),
                    "quote": s.get("fragment") or "",
                }
                for s in c.get("sources") or []
            ],
        }
        for c in raw.get("claims") or []
    ]
    shaped = {
        "status": raw.get("status", "ok"),
        "claims": claims,
        "unchecked_claims": raw.get("unchecked_claims") or [],
    }
    shaped.update({key: raw[key] for key in PASSTHROUGH if key in raw})
    # Scenario H: `moderator_loop` compares the case id of the first answer and the repeat.
    if case := raw.get("moderator_case"):
        shaped["moderator_case_id"] = case.get("id")
    return shaped


def image_data(payload: dict) -> str | None:
    """Scenario F: the case's image file (a path from the repository root) as base64."""
    path = payload.get("image")
    return base64.b64encode((ROOT / path).read_bytes()).decode() if path else None


def fault_headers(payload: dict) -> dict:
    """Headers that make the product simulate `payload["simulate"]` (scenario J), none without it.

    The product honours them only with its own PRAWDOWID_EVAL_TOKEN, which must be set here too.
    """
    fault = payload.get("simulate")
    if not fault:
        return {}
    token = os.environ.get("PRAWDOWID_EVAL_TOKEN")
    if not token:
        raise FaultNotApplied(
            f"fault {fault!r} not applied: set PRAWDOWID_EVAL_TOKEN (the product's value)"
        )
    return {"X-Eval-Fault": fault, "X-Eval-Token": token}


def require_private_transport(base: str) -> None:
    """The eval token must not cross a network in clear text: https, or http to this machine."""
    url = urllib.parse.urlsplit(base)
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            f"PRAWDOWID_URL {base!r} is plain http to a remote host: a case that simulates a "
            "fault sends the eval token, use https or a local tunnel"
        )


def confirm_fault(payload: dict, applied: str | None) -> None:
    """Refuses to score a fault case whose answer does not echo the fault (APPLIED_HEADER)."""
    fault = payload.get("simulate")
    if fault and applied != fault:
        raise FaultNotApplied(
            f"fault {fault!r} not applied: no matching {APPLIED_HEADER} in the response "
            "(PRAWDOWID_EVAL_TOKEN unset or different on the product?)"
        )


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """The default handler forwards every header, X-Eval-Token included, to the redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            return (
                None  # the 3xx surfaces as an HTTPError instead of leaving the origin
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SameOriginRedirects)


def ask(payload: dict, channel: str) -> dict:
    base = os.environ.get("PRAWDOWID_URL")
    if not base:
        raise RuntimeError(
            "PRAWDOWID_URL is not set, e.g. http://127.0.0.1:8000 (make dev)"
        )
    text = payload.get("text") or payload.get("url", "")
    image = image_data(payload)
    faults = fault_headers(payload)
    if faults:
        require_private_transport(base)
    if channel == "discord":
        raw, applied = asyncio.run(_ask_discord(base, text, faults, image))
        confirm_fault(payload, applied)
        return to_eval_shape(raw)
    body = json.dumps({"input": text, **({"image": image} if image else {})}).encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/api/checks",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Eval-Run": "1",
            "X-Channel": channel,
            **faults,
        },
    )
    try:
        response = _opener.open(request, timeout=TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        # A 429 or 5xx without the echo is not a product answer: the fault never ran.
        try:
            confirm_fault(payload, exc.headers.get(APPLIED_HEADER))
        except FaultNotApplied as missing:
            missing.retryable = exc.code == 429 or exc.code >= 500
            raise
        raise
    with response:
        confirm_fault(payload, response.headers.get(APPLIED_HEADER))
        shaped = to_eval_shape(json.loads(response.read().decode()))
        # Read by `evals.run.call`: an answer from the product's result cache says nothing about
        # how long a check takes.
        shaped["cached"] = response.headers.get("X-Cache") == "hit"
    return shaped


async def _ask_discord(
    base: str, text: str, headers: dict, image: str | None = None
) -> tuple[dict, str | None]:
    """The bot's answer and the fault echo of the response behind it."""
    applied: list[str | None] = []

    async def note_echo(response: httpx2.Response) -> None:
        applied.append(response.headers.get(APPLIED_HEADER))

    async with httpx2.AsyncClient(
        base_url=base,
        timeout=TIMEOUT_S,
        headers=headers,
        event_hooks={"response": [note_echo]},
    ) as client:
        check = await ask_api(text, client, image=image)
    return check.model_dump(mode="json"), next(iter(applied), None)
