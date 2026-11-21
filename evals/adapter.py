"""Calls the product under test. Contract: .claude/skills/prawdowid-eval/SKILL.md."""

from __future__ import annotations

import json
import os
import urllib.request

TIMEOUT_S = float(os.environ.get("PRAWDOWID_TIMEOUT_S", "90"))


def ask(payload: dict, channel: str) -> dict:
    base = os.environ.get("PRAWDOWID_URL")
    if not base:
        raise RuntimeError("PRAWDOWID_URL is not set, e.g. http://localhost:8000")
    body = json.dumps({**payload, "channel": channel}).encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/verify",
        data=body,
        headers={"Content-Type": "application/json", "X-Eval-Run": "1"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode())
