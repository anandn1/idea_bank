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

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    idea_id INTEGER,
    recurring INTEGER NOT NULL DEFAULT 0,
    target_date TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS goal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(goal_id, date)
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


def _migrate_from_v1_daily_goals(conn: sqlite3.Connection) -> None:
    """One-time bridge off the first cut of daily goals (idea-tag-based,
    required an idea, auto-completed via status change). Replaced by the
    standalone `goals`/`goal_log` model below. Empty in every real database
    this shipped to, so drop it outright; rename aside instead of dropping
    if it somehow isn't, so no history is ever silently destroyed.
    """
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "daily_goals" not in tables:
        return
    count = conn.execute("SELECT COUNT(*) AS n FROM daily_goals").fetchone()["n"]
    if count == 0:
        conn.execute("DROP TABLE daily_goals")
    else:
        conn.execute("ALTER TABLE daily_goals RENAME TO daily_goals_v1_backup")
    conn.commit()


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _ensure_fields_column(conn)
    _ensure_frontier_status(conn)
    _migrate_from_v1_daily_goals(conn)
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


# ---- goals ----
#
# A goal is its own thing -- its own text, e.g. "walk 10000 steps" -- not a
# tagged idea. It can optionally point at an idea (a concrete step toward
# that longer-term objective) but doesn't have to. A goal is either:
#   - recurring: due every day from its created_at date until it's stopped
#     (archived_at set), e.g. a daily habit
#   - one-off: due on exactly one target_date
# Completion is always self-reported into goal_log, one row per
# (goal_id, date) -- never derived from an idea's status, since most goals
# (the steps-walked example) have no idea, and thus no status, to derive
# from at all.


def today_str() -> str:
    return datetime.now().date().isoformat()


def create_goal(
    conn: sqlite3.Connection,
    text: str,
    idea_id: int | None = None,
    recurring: bool = False,
    target_date: str | None = None,
) -> dict | None:
    """Returns None if idea_id is given but doesn't exist. A recurring goal
    ignores target_date (it's due every day); a one-off goal defaults to
    today if target_date isn't given."""
    if idea_id is not None and get_idea(conn, idea_id) is None:
        return None
    if not recurring and target_date is None:
        target_date = today_str()
    if recurring:
        target_date = None

    cur = conn.execute(
        "INSERT INTO goals (text, idea_id, recurring, target_date, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (text, idea_id, 1 if recurring else 0, target_date, now_str()),
    )
    conn.commit()
    return get_goal(conn, cur.lastrowid)


def get_goal(conn: sqlite3.Connection, goal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return dict(row) if row else None


def missing_goal_ids(conn: sqlite3.Connection, goal_ids: list[int]) -> list[int]:
    placeholders = ",".join("?" * len(goal_ids))
    found = {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM goals WHERE id IN ({placeholders})", goal_ids
        )
    }
    return [i for i in goal_ids if i not in found]


def stop_goal(conn: sqlite3.Connection, goal_id: int) -> bool:
    """Archive a recurring goal so it stops being due -- history (past
    goal_log rows) is kept. No-op (returns False) for a one-off goal or one
    already stopped."""
    cur = conn.execute(
        "UPDATE goals SET archived_at = ? "
        "WHERE id = ? AND recurring = 1 AND archived_at IS NULL",
        (now_str(), goal_id),
    )
    conn.commit()
    return cur.rowcount > 0


def remove_goal(conn: sqlite3.Connection, goal_id: int) -> bool:
    """Hard-delete a goal definition and all of its completion history."""
    conn.execute("DELETE FROM goal_log WHERE goal_id = ?", (goal_id,))
    cur = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
    return cur.rowcount > 0


def unlink_goals_from_idea(conn: sqlite3.Connection, idea_id: int) -> None:
    """Called when an idea is deleted: the goal(s) that referenced it keep
    existing (and keep their history) -- they just lose the link, since
    completion was never derived from the idea in the first place."""
    conn.execute("UPDATE goals SET idea_id = NULL WHERE idea_id = ?", (idea_id,))


def goals_due_on(conn: sqlite3.Connection, date: str) -> list[dict]:
    """Every goal due on `date`: recurring goals active that day, plus
    one-off goals targeting it exactly. completed_at comes from goal_log if
    a row exists for that day, else NULL (nothing logged = not done)."""
    rows = conn.execute(
        "SELECT g.*, gl.completed_at AS completed_at "
        "FROM goals g "
        "LEFT JOIN goal_log gl ON gl.goal_id = g.id AND gl.date = ? "
        "WHERE (g.recurring = 1 AND date(g.created_at) <= date(?) "
        "       AND (g.archived_at IS NULL OR date(g.archived_at) > date(?))) "
        "   OR (g.recurring = 0 AND g.target_date = ?) "
        "ORDER BY g.created_at",
        (date, date, date, date),
    ).fetchall()
    return [dict(row) for row in rows]


def set_goal_done(
    conn: sqlite3.Connection, goal_id: int, date: str, done: bool
) -> dict | None:
    """Returns None (no-op) if the goal doesn't exist or isn't due on
    `date` -- e.g. a one-off goal targeting a different day, or a recurring
    goal not yet started/already stopped by then."""
    due = goals_due_on(conn, date)
    if not any(g["id"] == goal_id for g in due):
        return None
    if done:
        conn.execute(
            "INSERT INTO goal_log (goal_id, date, completed_at) VALUES (?, ?, ?) "
            "ON CONFLICT(goal_id, date) DO UPDATE SET completed_at = excluded.completed_at",
            (goal_id, date, now_str()),
        )
    else:
        conn.execute(
            "DELETE FROM goal_log WHERE goal_id = ? AND date = ?", (goal_id, date)
        )
    conn.commit()
    return next((g for g in goals_due_on(conn, date) if g["id"] == goal_id), None)


def _earliest_goal_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MIN(d) AS floor FROM ("
        "  SELECT date(created_at) AS d FROM goals WHERE recurring = 1"
        "  UNION ALL"
        "  SELECT target_date AS d FROM goals WHERE recurring = 0"
        ")"
    ).fetchone()
    return row["floor"]


def _day_is_won(due: list[dict]) -> bool | None:
    """True/False if `due` (goals_due_on's result for some day) settles the
    day; None if nothing was due at all, which neither wins nor breaks a
    streak -- a day before any goal existed, or after all were stopped."""
    if not due:
        return None
    return all(g["completed_at"] for g in due)


def compute_streak(conn: sqlite3.Connection, today: str | None = None) -> dict:
    """Walk backward from `today`, counting consecutive won days. A day with
    nothing due is skipped, not counted and not a break. An unfinished
    today doesn't break the streak -- it's just not counted until it's won."""
    from datetime import date as date_cls, timedelta

    today_d = date_cls.fromisoformat(today) if today else date_cls.today()
    floor = _earliest_goal_date(conn)

    today_due = goals_due_on(conn, today_d.isoformat())
    today_done = sum(1 for g in today_due if g["completed_at"])
    today_won = _day_is_won(today_due)

    streak = longest = run = 0
    if floor is not None:
        floor_d = date_cls.fromisoformat(floor)
        day = today_d if today_won else today_d - timedelta(days=1)
        d = floor_d
        while d <= today_d:
            won = _day_is_won(goals_due_on(conn, d.isoformat()))
            if won is None:
                d += timedelta(days=1)
                continue
            run = run + 1 if won else 0
            longest = max(longest, run)
            d += timedelta(days=1)

        d = day
        while d >= floor_d:
            won = _day_is_won(goals_due_on(conn, d.isoformat()))
            if won is None:
                d -= timedelta(days=1)
                continue
            if not won:
                break
            streak += 1
            d -= timedelta(days=1)

    return {
        "streak": streak,
        "longest": max(streak, longest),
        "today_complete": bool(today_won),
        "today_done": today_done,
        "today_total": len(today_due),
    }


def total_xp(conn: sqlite3.Connection) -> int:
    """Lifetime count of completed goal-days -- no arbitrary point weighting."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM goal_log WHERE completed_at IS NOT NULL"
    ).fetchone()
    return row["n"]
