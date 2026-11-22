"""Check log: one JSON line per check, per demo session.

A record holds the masked question, channel, start and end time, total and per-step latency, status
(with why a technical error happened), claims with verdicts, sources and limitations (search errors
and abstentions show up there), model calls with tokens, cost, security events, incident ids and the
moderator case the check joined. For an image, only its SHA-256 and the masked text read from it.

The question is stored masked (prawdowid/privacy.py; a link without its secret query values, see
`masked_question`), records older than `RETENTION_DAYS` are dropped on every write, and
`delete_session` removes every record of one session. Besides this
file, the moderator cases (prawdowid/cases.py) keep the masked claims of the checks a person should
look at, with the session id. Web search in a check also stores what it found, never user text or
a session id: the public pages it fetched in the source cache (`corpus/docs.jsonl`) and the hits
under a hash of the masked query (prawdowid/search_cache.py). A check never writes the database.
See docs/privacy.md.
"""

import fcntl
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prawdowid.contract import CheckResult
from prawdowid.link import redact
from prawdowid.privacy import RETENTION_DAYS, mask_personal_data
from prawdowid.verifier import is_link

log = logging.getLogger("prawdowid")

CHECK_LOG = Path(os.getenv("PRAWDOWID_CHECK_LOG") or "logs/checks.jsonl")
# When each session was last deleted: a check that started before that is never written, so a
# deletion also covers checks still running. ponytail: in memory, one uvicorn process (Dockerfile);
# a restart forgets it but also ends every running check. Move it into the log for several workers.
DELETED: dict[str, datetime] = {}


def masked_question(question: str) -> str:
    """The question as stored here and in the moderator cases: personal data masked, and a link
    without its secret query values (link.redact, as for the page URL)."""
    return mask_personal_data(redact(question) if is_link(question) else question)


def record(
    session: str,
    channel: str,
    question: str,
    result: CheckResult,
    *,
    started_at: datetime,
    latency_ms: int,
    error: str | None = None,
) -> None:
    """Append one check. A write failure is logged and never fails the check.

    `error` says why verify did not return ("timeout" or the exception class)."""
    page, image = result.page, result.image
    entry = {
        "session": session,
        # End of the check; retention counts from it.
        "time": datetime.now(UTC).isoformat(),
        "started_at": started_at.isoformat(),
        "latency_ms": latency_ms,
        "channel": channel,
        "question": masked_question(question),
        "status": result.status,
        "error": error,
        "message": result.message,
        "page": page and {"url": mask_personal_data(page.url), "sha256": page.sha256},
        # Never the image itself: its hash and the text read from it, masked again here.
        "image": image
        and {
            "sha256": image.sha256,
            "text": image.text and mask_personal_data(image.text),
        },
        "steps_ms": result.steps_ms,
        "model_calls": [m.model_dump() for m in result.model_calls],
        "cost_usd": result.cost_usd,
        "unpriced_requests": result.unpriced_requests,
        "security_events": [e.model_dump() for e in result.security_events],
        "incidents": [m.incident_id for m in result.incident_matches],
        "moderator_case": result.moderator_case and result.moderator_case.model_dump(),
        # Check-level limits, e.g. "patterns only" when the model did not answer.
        "limitations": [mask_personal_data(x) for x in result.limitations],
        "claims": [
            {
                "claim": mask_personal_data(c.claim),
                "verdict": c.verdict,
                "sources": [
                    {
                        "url": mask_personal_data(str(s.url)),
                        "source_type": s.source_type,
                    }
                    for s in c.sources
                ],
                "limitations": [mask_personal_data(x) for x in c.limitations],
                "steps_ms": c.steps_ms,
            }
            for c in result.claims
        ],
        "unchecked_claims": [mask_personal_data(c) for c in result.unchecked_claims],
    }
    if session in DELETED and started_at <= DELETED[session]:
        return
    try:
        # ponytail: rewrites the file on every check to apply retention; fine for a demo log.
        _rewrite(_fresh, [entry])
    except OSError as exc:
        log.warning("check log write failed: %r", exc)


def read_session(session: str) -> list[dict]:
    """Every record of the session, oldest first. Writers swap the file atomically, so no lock."""
    path = CHECK_LOG
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [
        r for r in map(_parse, lines) if r and r["session"] == session and _fresh(r)
    ]


def delete_session(session: str) -> int:
    """Delete every record of the session, also of checks still running. Number deleted."""
    DELETED[session] = datetime.now(UTC)
    return _rewrite(lambda r: r["session"] != session)


def _fresh(r: dict) -> bool:
    """Within retention."""
    return datetime.fromisoformat(r["time"]) > datetime.now(UTC) - timedelta(
        days=RETENTION_DAYS
    )


def _rewrite(keep, extra: list[dict] = ()) -> int:
    """Keep the records `keep` accepts, append `extra`. Number of records dropped."""
    path = CHECK_LOG  # looked up per call, so tests can point it elsewhere
    path.parent.mkdir(parents=True, exist_ok=True)
    # One writer at a time, across threads and processes: each call opens its own descriptor, and
    # flock locks per descriptor. Without it two writers read the same file and one record is lost.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _rewrite_locked(path, keep, extra)


def _rewrite_locked(path: Path, keep, extra: list[dict]) -> int:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    records = [r for r in map(_parse, lines) if r]
    kept = [r for r in records if keep(r)] + list(extra)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept),
        encoding="utf-8",
    )
    tmp.replace(path)
    return len(records) + len(extra) - len(kept)


def _parse(line: str) -> dict | None:
    """One record, or None for a damaged line: it is dropped on the next rewrite, so it never
    blocks logging or deletion."""
    try:
        r = json.loads(line)
        datetime.fromisoformat(r["time"])
        r["session"]
    except (ValueError, TypeError, KeyError):
        return None
    return r
