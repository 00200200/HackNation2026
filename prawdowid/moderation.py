"""Moderator loop (scenario H): a question we could not answer opens a case for a human moderator.

The same question asked again maps to the same case (the id is a hash of the masked, normalised
question), so repeats add up instead of opening new cases. A moderator answers a case in the panel
(`/moderator.html`, token in `PRAWDOWID_MODERATOR_TOKEN`); later checks of that question show the
answer next to the automatic result. The answer is a human note and never sets or changes a verdict.

Only the masked question is stored, never a session or channel. Cases not asked for
`RETENTION_DAYS` are dropped whenever the store is used.
"""

import hashlib
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from prawdowid.privacy import RETENTION_DAYS, mask_personal_data

DB = Path(os.getenv("PRAWDOWID_MODERATION_DB") or "logs/moderation.sqlite3")
MAX_ANSWER_CHARS = 2000
SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    asked INTEGER NOT NULL,
    first_asked TEXT NOT NULL,
    last_asked TEXT NOT NULL,
    answer TEXT,
    answered_at TEXT
)
"""


class Case(BaseModel):
    id: str
    question: str
    asked: int
    first_asked: datetime
    last_asked: datetime
    answer: str | None = None
    answered_at: datetime | None = None


def case_id(question: str) -> str:
    """Same id for the same question, whatever its case, spacing or closing punctuation. 64 bits,
    so nobody can craft another question that lands on an answered case."""
    text = re.sub(r"\s+", " ", mask_personal_data(question)).strip(" ?!.").casefold()
    return hashlib.sha256(text.encode()).hexdigest()[:16].upper()


def open_case(question: str) -> Case:
    """The question's case, opened now or counted once more."""
    now = _now()
    with _db() as db:
        db.execute(
            "INSERT INTO cases (id, question, asked, first_asked, last_asked)"
            " VALUES (?, ?, 1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET asked = asked + 1, last_asked = excluded.last_asked",
            (
                case_id(question),
                mask_personal_data(question),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return get(case_id(question))


def get(id: str) -> Case | None:
    with _db() as db:
        row = db.execute("SELECT * FROM cases WHERE id = ?", (id,)).fetchone()
    return Case(**row) if row else None


def list_cases() -> list[Case]:
    """Open cases first, then the most asked, then the most recent."""
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM cases ORDER BY answer IS NOT NULL, asked DESC, last_asked DESC"
        ).fetchall()
    return [Case(**r) for r in rows]


def answer(id: str, text: str) -> Case | None:
    """Store or replace the moderator's answer. None when there is no such case."""
    with _db() as db:
        db.execute(
            "UPDATE cases SET answer = ?, answered_at = ? WHERE id = ?",
            (text, _now().isoformat(), id),
        )
    return get(id)


def _db() -> closing[sqlite3.Connection]:
    """A connection per call; sqlite serialises writers across threads and processes."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=5, isolation_level=None)  # autocommit
    db.row_factory = sqlite3.Row
    db.execute(SCHEMA)
    # Retention on every use, so the panel never lists, and nobody answers, an expired case.
    db.execute(
        "DELETE FROM cases WHERE last_asked < ?",
        ((_now() - timedelta(days=RETENTION_DAYS)).isoformat(),),
    )
    return closing(db)


def _now() -> datetime:
    return datetime.now(UTC)
