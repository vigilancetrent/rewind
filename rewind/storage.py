"""SQLite-backed event store for rewind traces."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rewind.types import ProviderCall, Trace

DEFAULT_DB_PATH = Path.home() / ".rewind" / "traces.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    name     TEXT PRIMARY KEY,
    started  TEXT NOT NULL,
    ended    TEXT,
    notes    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS calls (
    trace        TEXT    NOT NULL,
    step         INTEGER NOT NULL,
    ts           REAL    NOT NULL,
    provider     TEXT    NOT NULL,
    model        TEXT    NOT NULL,
    messages_json TEXT   NOT NULL,
    response     TEXT    NOT NULL,
    in_toks      INTEGER NOT NULL DEFAULT 0,
    out_toks     INTEGER NOT NULL DEFAULT 0,
    cached_toks  INTEGER NOT NULL DEFAULT 0,
    cost         REAL,
    latency_ms   REAL    NOT NULL DEFAULT 0,
    metadata_json TEXT   NOT NULL DEFAULT '{}',
    PRIMARY KEY (trace, step),
    FOREIGN KEY (trace) REFERENCES traces(name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_calls_trace_ts ON calls(trace, ts);
"""


def _resolve_path(db_path: str | os.PathLike[str] | None) -> Path:
    p = Path(db_path) if db_path else DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def init_db(db_path: str | os.PathLike[str] | None = None) -> Path:
    """Create the schema if needed. Idempotent."""
    path = _resolve_path(db_path)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    return path


@contextmanager
def connect(db_path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    path = _resolve_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_trace(name: str, started_at: str, db_path: str | os.PathLike[str] | None = None,
                 notes: str = "") -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO traces (name, started, ended, notes) VALUES (?, ?, NULL, ?)",
            (name, started_at, notes),
        )


def finalize_trace(name: str, ended_at: str,
                   db_path: str | os.PathLike[str] | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE traces SET ended = ? WHERE name = ?", (ended_at, name))


def append_call(trace_name: str, call: ProviderCall,
                db_path: str | os.PathLike[str] | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO calls
            (trace, step, ts, provider, model, messages_json, response,
             in_toks, out_toks, cached_toks, cost, latency_ms, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_name,
                call.step,
                call.timestamp,
                call.provider,
                call.model,
                json.dumps(call.messages, default=str),
                call.response_text,
                call.input_tokens,
                call.output_tokens,
                call.cached_tokens,
                call.cost_usd,
                call.latency_ms,
                json.dumps(call.metadata, default=str),
            ),
        )


def list_traces(db_path: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return trace summaries sorted most-recent-first."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.name, t.started, t.ended, t.notes,
                   COUNT(c.step) AS n_calls,
                   COALESCE(SUM(c.cost), 0) AS total_cost,
                   COALESCE(SUM(c.in_toks), 0) AS total_in,
                   COALESCE(SUM(c.out_toks), 0) AS total_out
            FROM traces t LEFT JOIN calls c ON c.trace = t.name
            GROUP BY t.name
            ORDER BY t.started DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_trace(name: str, db_path: str | os.PathLike[str] | None = None) -> Trace | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT name, started, ended, notes FROM traces WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        calls = get_calls(name, db_path=db_path)
    return Trace(name=row["name"], started_at=row["started"], ended_at=row["ended"],
                 notes=row["notes"], calls=calls)


def get_calls(trace_name: str,
              db_path: str | os.PathLike[str] | None = None) -> list[ProviderCall]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT step, ts, provider, model, messages_json, response,
                   in_toks, out_toks, cached_toks, cost, latency_ms, metadata_json
            FROM calls WHERE trace = ? ORDER BY step ASC
            """,
            (trace_name,),
        ).fetchall()
    out: list[ProviderCall] = []
    for r in rows:
        out.append(ProviderCall(
            step=r["step"],
            timestamp=r["ts"],
            provider=r["provider"],
            model=r["model"],
            messages=json.loads(r["messages_json"]),
            response_text=r["response"],
            input_tokens=r["in_toks"],
            output_tokens=r["out_toks"],
            cached_tokens=r["cached_toks"],
            cost_usd=r["cost"],
            latency_ms=r["latency_ms"],
            metadata=json.loads(r["metadata_json"]),
        ))
    return out


def delete_trace(name: str, db_path: str | os.PathLike[str] | None = None) -> int:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM traces WHERE name = ?", (name,))
        return cur.rowcount


def next_step(trace_name: str, db_path: str | os.PathLike[str] | None = None) -> int:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(step), -1) AS max_step FROM calls WHERE trace = ?",
            (trace_name,),
        ).fetchone()
    return int(row["max_step"]) + 1
