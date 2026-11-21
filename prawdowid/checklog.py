"""Check log: one JSON line per check (question, time, result, sources), per demo session.

The question is stored masked (prawdowid/privacy.py), records older than `RETENTION_DAYS` are
dropped on every write, and `delete_session` removes every record of one session. This file is the
only place a check is kept: the source cache and the database are never written by a check.
"""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prawdowid.contract import CheckResult
from prawdowid.privacy import RETENTION_DAYS, mask_personal_data

log = logging.getLogger("prawdowid")

CHECK_LOG = Path(os.getenv("PRAWDOWID_CHECK_LOG") or "logs/checks.jsonl")


def record(
    session: str,
    channel: str,
    question: str,
    result: CheckResult,
) -> None:
    """Append one check. A write failure is logged and never fails the check."""
    entry = {
        "session": session,
        "time": datetime.now(UTC).isoformat(),
        "channel": channel,
        "question": mask_personal_data(question),
        "status": result.status,
        "claims": [
            {
                "claim": c.claim,
                "verdict": c.verdict,
                "sources": [str(s.url) for s in c.sources],
            }
            for c in result.claims
        ],
        "unchecked_claims": result.unchecked_claims,
    }
    try:
        # ponytail: rewrites the file on every check to apply retention; fine for a demo log.
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        _rewrite(lambda r: datetime.fromisoformat(r["time"]) > cutoff, [entry])
    except OSError as exc:
        log.warning("check log write failed: %r", exc)


def delete_session(session: str) -> int:
    """Delete every record of the session. Number of records deleted."""
    return _rewrite(lambda r: r["session"] != session)


def _rewrite(keep, extra: list[dict] = ()) -> int:
    """Keep the records `keep` accepts, append `extra`. Number of records dropped."""
    path = CHECK_LOG  # looked up per call, so tests can point it elsewhere
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    records = [r for r in map(_parse, lines) if r]
    kept = [r for r in records if keep(r)] + list(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
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
