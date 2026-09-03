"""Shared SQLite access for idea-bank-v2 (server, CLI, and scripts).

Kept dependency-free (stdlib only) so the CLI works without the venv active.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "ideas.db"

STATUSES = ("inbox", "active", "queued", "horizon", "archive")

IDEA_COLUMNS = "id, text, status, created_at, updated_at, notes"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('inbox','active','queued','horizon','archive')) DEFAULT 'inbox',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_line TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flagged_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_line TEXT NOT NULL,
    reason TEXT NOT NULL,
    flagged_at TEXT NOT NULL
);
"""


def now_str() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def connection():
    """Open a connection, commit on clean exit, always close.

    Callers still call conn.commit() explicitly after writes (so a
    read-only caller can skip it), but the connection is guaranteed to
    close even if an exception is raised.
    """
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def add_idea(text: str, status: str = "inbox", created_at: str | None = None) -> int:
    ts = created_at or now_str()
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO ideas (text, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (text, status, ts, ts),
        )
        conn.commit()
        return cur.lastrowid


def get_idea(conn: sqlite3.Connection, idea_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {IDEA_COLUMNS} FROM ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    return dict(row) if row else None
