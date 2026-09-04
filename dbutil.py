"""Shared SQLite access for idea-bank-v2 (server, CLI, and scripts).

Kept dependency-free (stdlib only) so the CLI works without the venv active.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# IDEA_BANK_DB_PATH overrides the default location -- used by the test
# suite (subprocess-invoked CLI tests) to point at an isolated DB file
# instead of the real one. Unset in normal use.
DB_PATH = Path(
    os.environ.get("IDEA_BANK_DB_PATH")
    or (Path(__file__).resolve().parent / "data" / "ideas.db")
)

STATUSES = ("inbox", "active", "queued", "horizon", "frontier", "archive")

IDEA_COLUMNS = "id, text, status, created_at, updated_at, notes, fields"

STATUS_CHECK = (
    "CHECK(status IN ('inbox','active','queued','horizon','frontier','archive'))"
)

IDEAS_TABLE = f"""
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL {STATUS_CHECK} DEFAULT 'inbox',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT,
    fields TEXT
);
"""

SCHEMA = f"""
{IDEAS_TABLE}

CREATE TABLE IF NOT EXISTS daily_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    idea_id INTEGER NOT NULL,
    idea_text_snapshot TEXT NOT NULL,
    status_at_tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(date, idea_id)
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


def _ensure_fields_column(conn: sqlite3.Connection) -> None:
    """Add the `fields` column to a pre-existing ideas table that predates it.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, so check first; this makes
    the migration safe to run on every connection.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
    if "fields" not in columns:
        conn.execute("ALTER TABLE ideas ADD COLUMN fields TEXT")


def _ensure_frontier_status(conn: sqlite3.Connection) -> None:
    """Widen a pre-existing ideas table's status CHECK to allow 'frontier'.

    SQLite can't ALTER a CHECK constraint, and `CREATE TABLE IF NOT EXISTS`
    won't touch a table that already exists -- so a database created before
    'frontier' would reject every write of it. Rebuild the table instead:
    the standard rename/create/copy/drop dance, guarded so it runs once.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ideas'"
    ).fetchone()
    if row is None or "frontier" in row["sql"]:
        return

    conn.executescript(f"""
        BEGIN;
        ALTER TABLE ideas RENAME TO ideas_pre_frontier;
        {IDEAS_TABLE}
        INSERT INTO ideas ({IDEA_COLUMNS})
            SELECT {IDEA_COLUMNS} FROM ideas_pre_frontier;
        DROP TABLE ideas_pre_frontier;
        COMMIT;
        """)


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _ensure_fields_column(conn)
    _ensure_frontier_status(conn)
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


def encode_fields(fields: dict | None) -> str | None:
    """Structured fields are entirely optional: nothing set -> NULL in the
    DB and an empty {} wherever an idea is returned, never a required
    column a caller has to think about."""
    return json.dumps(fields) if fields else None


def row_to_idea(row: sqlite3.Row) -> dict:
    idea = dict(row)
    idea["fields"] = json.loads(idea["fields"]) if idea.get("fields") else {}
    return idea


def add_idea(
    text: str,
    status: str = "inbox",
    created_at: str | None = None,
    fields: dict | None = None,
) -> int:
    ts = created_at or now_str()
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO ideas (text, status, created_at, updated_at, fields) "
            "VALUES (?, ?, ?, ?, ?)",
            (text, status, ts, ts, encode_fields(fields)),
        )
        conn.commit()
        return cur.lastrowid


def get_idea(conn: sqlite3.Connection, idea_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {IDEA_COLUMNS} FROM ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    return row_to_idea(row) if row else None


# ---- daily goals ----
#
# A goal is an existing idea tagged for a given calendar day. Completion is
# derived, not set directly: tagging snapshots the idea's status, and the
# goal is "done" the moment the idea's live status differs from that
# snapshot. sync_goal_completion() is the only place that stamps
# completed_at, and every read below calls it first, so completion never
# depends on hooking every status-change code path (CLI move, PATCH,
# drag-drop, the expiry sweep) -- it's just derived from current state.


def today_str() -> str:
    return datetime.now().date().isoformat()


def add_goal(conn: sqlite3.Connection, idea_id: int, date: str) -> dict | None:
    """Tag an idea as a goal for `date`. Re-tagging an already-tagged idea
    is a no-op, not an error. Returns None if the idea doesn't exist."""
    idea = get_idea(conn, idea_id)
    if idea is None:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO daily_goals "
        "(date, idea_id, idea_text_snapshot, status_at_tag, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (date, idea_id, idea["text"], idea["status"], now_str()),
    )
    conn.commit()
    return get_goal(conn, date, idea_id)


def remove_goal(conn: sqlite3.Connection, idea_id: int, date: str) -> bool:
    cur = conn.execute(
        "DELETE FROM daily_goals WHERE date = ? AND idea_id = ?", (date, idea_id)
    )
    conn.commit()
    return cur.rowcount > 0


def remove_goals_for_idea(conn: sqlite3.Connection, idea_id: int) -> None:
    """Called when an idea is deleted: a goal pointing at a deleted idea
    could never complete and would silently freeze the streak forever."""
    conn.execute("DELETE FROM daily_goals WHERE idea_id = ?", (idea_id,))


def sync_goal_completion(conn: sqlite3.Connection) -> None:
    """Stamp completed_at on any goal whose idea has moved off its
    snapshotted status. Sticky: moving the idea back doesn't un-win it."""
    conn.execute(
        "UPDATE daily_goals SET completed_at = ? "
        "WHERE completed_at IS NULL AND EXISTS ("
        "  SELECT 1 FROM ideas WHERE ideas.id = daily_goals.idea_id "
        "  AND ideas.status != daily_goals.status_at_tag"
        ")",
        (now_str(),),
    )
    conn.commit()


def get_goal(conn: sqlite3.Connection, date: str, idea_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM daily_goals WHERE date = ? AND idea_id = ?", (date, idea_id)
    ).fetchone()
    return dict(row) if row else None


def goals_for_date(conn: sqlite3.Connection, date: str) -> list[dict]:
    sync_goal_completion(conn)
    rows = conn.execute(
        "SELECT * FROM daily_goals WHERE date = ? ORDER BY created_at", (date,)
    ).fetchall()
    return [dict(row) for row in rows]


def completed_dates(conn: sqlite3.Connection) -> set[str]:
    """Every date with at least one goal, where all of that date's goals
    are complete."""
    sync_goal_completion(conn)
    rows = conn.execute(
        "SELECT date, COUNT(*) AS total, "
        "       SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) AS done "
        "FROM daily_goals GROUP BY date"
    ).fetchall()
    return {
        row["date"] for row in rows if row["total"] > 0 and row["done"] == row["total"]
    }


def _longest_streak(days: set[str]) -> int:
    from datetime import date as date_cls

    parsed = sorted(date_cls.fromisoformat(d) for d in days)
    longest = run = 0
    prev = None
    for day in parsed:
        run = run + 1 if prev is not None and (day - prev).days == 1 else 1
        longest = max(longest, run)
        prev = day
    return longest


def compute_streak(conn: sqlite3.Connection, today: str | None = None) -> dict:
    """Count consecutive complete days ending at `today` (default: the real
    current date). An unfinished today doesn't break the streak -- it's
    just not counted until it's done."""
    from datetime import date as date_cls, timedelta

    today_d = date_cls.fromisoformat(today) if today else date_cls.today()
    done = completed_dates(conn)

    today_complete = today_d.isoformat() in done
    day = today_d if today_complete else today_d - timedelta(days=1)
    streak = 0
    while day.isoformat() in done:
        streak += 1
        day -= timedelta(days=1)

    goals_today = goals_for_date(conn, today_d.isoformat())
    today_done = sum(1 for g in goals_today if g["completed_at"])

    return {
        "streak": streak,
        "longest": max(streak, _longest_streak(done)),
        "today_complete": today_complete,
        "today_done": today_done,
        "today_total": len(goals_today),
    }


def total_xp(conn: sqlite3.Connection) -> int:
    """Lifetime count of completed goals -- no arbitrary point weighting."""
    sync_goal_completion(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM daily_goals WHERE completed_at IS NOT NULL"
    ).fetchone()
    return row["n"]
