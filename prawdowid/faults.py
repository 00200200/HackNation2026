"""Eval-only fault switch for scenario J: the harness asks the product to behave as if a
dependency were down, so the outage path is scored without breaking a real key.

A request carries `X-Eval-Fault: <fault>` and `X-Eval-Token: <secret>`. The fault is honoured only
when PRAWDOWID_EVAL_TOKEN is set on the server and the token matches (constant-time compare), so a
public user cannot set it, and on a server without the variable the headers do nothing.
"""

import hmac
import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

log = logging.getLogger("prawdowid")

TOKEN_ENV = "PRAWDOWID_EVAL_TOKEN"
FACTCHECK_UNAVAILABLE = "factcheck_api_unavailable"
LLM_UNAVAILABLE = "llm_unavailable"
# Response header: the fault this request applied. Only set when `requested` accepted the token,
# so the harness can tell a simulated outage from a healthy run (a missing or wrong token is silent).
APPLIED_HEADER = "X-Eval-Fault-Applied"
FAULTS = frozenset({FACTCHECK_UNAVAILABLE, LLM_UNAVAILABLE})

# A ContextVar follows the request into the tasks and threads it starts.
_active: ContextVar[str | None] = ContextVar("eval_fault", default=None)


def requested(headers: Mapping[str, str]) -> str | None:
    """The fault this request may simulate: None unless the eval token is valid."""
    fault = headers.get("x-eval-fault")
    token = os.getenv(TOKEN_ENV)
    if not fault or not token:
        return None
    given = headers.get("x-eval-token", "")
    if not hmac.compare_digest(given.encode(), token.encode()):
        log.warning("eval fault refused: wrong token")
        return None
    if fault not in FAULTS:
        log.warning("eval fault refused: unknown fault %r", fault)
        return None
    return fault


def active(fault: str) -> bool:
    return _active.get() == fault


@contextmanager
def simulate(fault: str | None) -> Iterator[None]:
    token = _active.set(fault)
    try:
        yield
    finally:
        _active.reset(token)
