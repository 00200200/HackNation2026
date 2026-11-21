"""Calls the product under test and maps its answer to the eval's internal shape.

Product API: POST /api/checks with {"input": "..."}, returns CheckResult (prawdowid/contract.py).
Notes on the contract and its gaps: .claude/skills/prawdowid-eval/SKILL.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

import httpx2

from prawdowid.discord_bot import ask_api

TIMEOUT_S = float(os.environ.get("PRAWDOWID_TIMEOUT_S", "90"))
# The API allows 10 requests per minute per client; stay under it.
MIN_INTERVAL_S = float(os.environ.get("PRAWDOWID_MIN_INTERVAL_S", "6.5"))
# Channels besides the web API, comma-separated. "discord" runs the bot's own API client
# (prawdowid/discord_bot.ask_api), so only the Discord connection itself is not exercised.
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
PASSTHROUGH = ("security_events", "cost_usd", "moderator_case_id")

_last_call = 0.0


def supports(channel: str) -> bool:
    return channel in CHANNELS


def wait_turn() -> None:
    """Sleep so that consecutive requests respect the API rate limit."""
    global _last_call
    delay = _last_call + MIN_INTERVAL_S - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    _last_call = time.monotonic()


def to_eval_shape(raw: dict) -> dict:
    claims = [
        {
            "text": c.get("claim", ""),
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
    shaped = {"status": raw.get("status", "ok"), "claims": claims}
    shaped.update({key: raw[key] for key in PASSTHROUGH if key in raw})
    return shaped


def ask(payload: dict, channel: str) -> dict:
    base = os.environ.get("PRAWDOWID_URL")
    if not base:
        raise RuntimeError(
            "PRAWDOWID_URL is not set, e.g. http://127.0.0.1:8000 (make dev)"
        )
    text = payload.get("text") or payload.get("url", "")
    if channel == "discord":
        return to_eval_shape(asyncio.run(_ask_discord(base, text)))
    body = json.dumps({"input": text}).encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/api/checks",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Eval-Run": "1",
            "X-Channel": channel,
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return to_eval_shape(json.loads(response.read().decode()))


async def _ask_discord(base: str, text: str) -> dict:
    async with httpx2.AsyncClient(base_url=base, timeout=TIMEOUT_S) as client:
        check = await ask_api(text, client)
    return check.model_dump(mode="json")
