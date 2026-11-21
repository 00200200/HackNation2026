"""Check log: one SQLite table, one row per check."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from prawdowid.contract import CheckResult

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "checks.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    channel TEXT NOT NULL,
    input TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    model_name TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_usd REAL,
    abstained INTEGER,
    security_events TEXT
);
CREATE INDEX IF NOT EXISTS checks_session ON checks (session_id);
"""


def db_path() -> Path:
    return Path(os.environ.get("PRAWDOWID_DB_PATH", DEFAULT_DB_PATH))


def connect() -> closing[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return closing(conn)


def init() -> None:
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def add(
    *,
    session_id: str | None,
    channel: str,
    input: str,
    result: CheckResult,
    latency_ms: int,
) -> str:
    check_id = uuid.uuid4().hex
    with connect() as conn, conn:
        conn.execute(
            "INSERT INTO checks (id, session_id, channel, input, created_at, status, result, latency_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                check_id,
                session_id,
                channel,
                input,
                datetime.now(UTC).isoformat(),
                result.status,
                result.model_dump_json(),
                latency_ms,
            ),
        )
    return check_id


def _row(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["result"] = json.loads(record["result"])
    record["security_events"] = json.loads(record["security_events"] or "null")
    record["abstained"] = (
        None if record["abstained"] is None else bool(record["abstained"])
    )
    return record


def get(check_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
    return row and _row(row)


def list_all() -> list[dict]:
    # ponytail: no pagination, fine for a demo-sized log; add limit/offset if it grows.
    with connect() as conn:
        rows = conn.execute("SELECT * FROM checks ORDER BY created_at DESC").fetchall()
    return [_row(r) for r in rows]


def delete_session(session_id: str) -> int:
    with connect() as conn, conn:
        return conn.execute(
            "DELETE FROM checks WHERE session_id = ?", (session_id,)
        ).rowcount
