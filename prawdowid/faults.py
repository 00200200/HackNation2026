"""Eval-only fault switch for scenario J: a missing key, a rate limit or a dependency outage.

Off unless the server runs with PRAWDOWID_EVAL_FAULTS=1 (Compose never passes it to a container).
Then the eval harness names one fault per request in the X-Eval-Fault header. A fault raises the
error the real dependency raises, at the place it raises it, so the product's own outage handling
decides the answer.
"""

import logging
import os
from contextvars import ContextVar

from pydantic_ai.exceptions import ModelHTTPError, UserError

log = logging.getLogger("prawdowid")

ENV = "PRAWDOWID_EVAL_FAULTS"
HEADER = "X-Eval-Fault"
FACTCHECK_DOWN = "factcheck_api_unavailable"
# What the extraction model call raises for each fault (verifier._extract handles them).
MODEL_ERRORS = {
    "llm_unavailable": lambda: ModelHTTPError(503, "eval-fault"),
    "llm_rate_limited": lambda: ModelHTTPError(429, "eval-fault"),
    # The provider's own error when ANTHROPIC_API_KEY is not set.
    "llm_key_missing": lambda: UserError("Set the `ANTHROPIC_API_KEY` (eval fault)"),
}
FAULTS = {FACTCHECK_DOWN, *MODEL_ERRORS}

# The fault of the current request; tasks started inside verify() inherit it.
active: ContextVar[str | None] = ContextVar("eval_fault", default=None)


def requested(header: str | None) -> str | None:
    """The fault named in the request header, or None when the switch is off."""
    if not header or os.getenv(ENV) != "1":
        return None
    if header not in FAULTS:
        log.warning("unknown eval fault %r ignored", header)
        return None
    log.warning("eval fault active: %s", header)
    return header


def model_error() -> Exception | None:
    make = MODEL_ERRORS.get(active.get())
    return make() if make else None
