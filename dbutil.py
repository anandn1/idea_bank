"""Shared SQLite access for idea-bank-v2 (server, CLI, and scripts).

The only non-stdlib dependency is `cryptography`, used for encrypting
free-text content at rest (see the "privacy" section below). It's listed in
requirements.txt (installed into .venv by install.sh) and is needed by the
CLI too, which runs on the system python3, not the venv -- so if it's not
on the system path either, fall back to .venv's copy rather than requiring
every machine to have it installed system-wide.
"""

import glob
import json
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:
    _venv_site_packages = glob.glob(
        str(
            Path(__file__).resolve().parent
            / ".venv"
            / "lib"
            / "python3.*"
            / "site-packages"
        )
    )
    if not _venv_site_packages:
        raise
    sys.path.insert(0, _venv_site_packages[0])
    from cryptography.fernet import Fernet

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

GOAL_COLUMNS = "id, text, weekdays, target_date, created_at, archived_at"

GOALS_TABLE = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    weekdays TEXT,
    target_date TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
"""

SCHEMA = f"""
{IDEAS_TABLE}

{GOALS_TABLE}

CREATE TABLE IF NOT EXISTS goal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(goal_id, date)
);

-- a goal can link to more than one idea (and an idea can have more than
-- one goal, already true before this table existed) -- see
-- _ensure_goal_ideas_join_table for the migration off the old single
-- idea_id column.
CREATE TABLE IF NOT EXISTS goal_ideas (
    goal_id INTEGER NOT NULL,
    idea_id INTEGER NOT NULL,
    PRIMARY KEY (goal_id, idea_id)
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


# ---- privacy: encryption at rest ----
#
# Every free-text column (idea text/notes/fields, goal text, and the raw
# lines migrate.py logs) is encrypted before it's ever written to
# data/ideas.db, so the .db file itself is opaque -- a dev with the source
# code and the database but not this key can't read a single idea. The key
# lives outside the repo, at KEY_PATH (mode 0600, generated on first use),
# so it's never committed and never travels with the database file.
#
# Columns that drive SQL (status, dates, ids) stay plaintext -- they're not
# personal content and encrypting them would break WHERE/ORDER BY/CHECK.

KEY_PATH = Path(
    os.environ.get("IDEA_BANK_KEY_PATH")
    or (Path.home() / ".config" / "idea-bank" / "secret.key")
)

ENC_PREFIX = "enc1:"


def _fernet() -> Fernet:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not KEY_PATH.exists():
        try:
            fd = os.open(KEY_PATH, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass  # lost a race with another process creating it first
    return Fernet(KEY_PATH.read_bytes())


def encrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    return ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str | None) -> str | None:
    """Passes a value through unchanged if it has no ENC_PREFIX -- covers
    both a row `_ensure_encrypted_content` hasn't reached yet and plaintext
    written straight to the table (bypassing encrypt_str) rather than
    failing to decrypt."""
    if value is None or not value.startswith(ENC_PREFIX):
        return value
    return _fernet().decrypt(value[len(ENC_PREFIX) :].encode()).decode()


def _encrypt_unmigrated_rows(
    conn: sqlite3.Connection, table: str, columns: list[str]
) -> None:
    """Encrypt `columns` in every row of `table` that's still plaintext,
    judged by the first column having no ENC_PREFIX. One row at a time
    (not a bulk UPDATE) because each value needs its own Fernet token."""
    select_cols = ", ".join(["id", *columns])
    set_clause = ", ".join(f"{column} = ?" for column in columns)
    for row in conn.execute(f"SELECT {select_cols} FROM {table}"):
        if (row[columns[0]] or "").startswith(ENC_PREFIX):
            continue
        values = [encrypt_str(row[column]) for column in columns]
        conn.execute(
            f"UPDATE {table} SET {set_clause} WHERE id = ?", [*values, row["id"]]
        )


def _ensure_encrypted_content(conn: sqlite3.Connection) -> None:
    """One-time-per-row sweep that encrypts any legacy plaintext content
    left over from before encryption existed. Idempotent: a row already
    encrypted (ENC_PREFIX present) is skipped, so this is cheap after the
    first run, same as the other migrations above."""
    _encrypt_unmigrated_rows(conn, "ideas", ["text", "notes", "fields"])
    _encrypt_unmigrated_rows(conn, "goals", ["text"])
    _encrypt_unmigrated_rows(conn, "import_log", ["raw_line"])
    _encrypt_unmigrated_rows(conn, "flagged_imports", ["raw_line", "reason"])
    conn.commit()


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


def _ensure_goal_weekdays(conn: sqlite3.Connection) -> None:
    """Replace the boolean `recurring` column with `weekdays` (a comma-
    joined set of Python date.weekday() values, Monday=0..Sunday=6; NULL
    means one-off, using target_date same as before). SQLite can't drop a
    column in place any more than it can ALTER a CHECK constraint -- same
    rename/create/copy/drop dance as _ensure_frontier_status, guarded so it
    runs once. Backfill: an old recurring=1 row becomes due every day of
    the week; recurring=0 keeps its target_date, gets no weekdays.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'goals'"
    ).fetchone()
    if row is None or "weekdays" in row["sql"]:
        return

    # Deliberately NOT {GOALS_TABLE}/{GOAL_COLUMNS} here -- those describe
    # the *current* schema, which has moved on since this migration was
    # written (idea_id later became its own join table). This migration's
    # job is frozen in history: produce the goals shape as it stood right
    # after weekdays replaced recurring, still with idea_id -- a later
    # migration (_ensure_goal_ideas_join_table) takes it from there.
    conn.executescript("""
        BEGIN;
        ALTER TABLE goals RENAME TO goals_pre_weekdays;
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            idea_id INTEGER,
            weekdays TEXT,
            target_date TEXT,
            created_at TEXT NOT NULL,
            archived_at TEXT
        );
        INSERT INTO goals (id, text, idea_id, weekdays, target_date, created_at, archived_at)
            SELECT id, text, idea_id,
                   CASE WHEN recurring = 1 THEN '0,1,2,3,4,5,6' ELSE NULL END,
                   target_date, created_at, archived_at
            FROM goals_pre_weekdays;
        DROP TABLE goals_pre_weekdays;
        COMMIT;
        """)


def _ensure_goal_ideas_join_table(conn: sqlite3.Connection) -> None:
    """Replace the single idea_id column with the goal_ideas join table, so
    a goal can link to more than one idea. Same rename/create/copy/drop
    dance as the other goal-schema migrations, guarded so it runs once.
    Backfill: an old non-NULL idea_id becomes one row in goal_ideas.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'goals'"
    ).fetchone()
    if row is None or "idea_id" not in row["sql"]:
        return

    conn.executescript(f"""
        BEGIN;
        ALTER TABLE goals RENAME TO goals_pre_join_ideas;
        {GOALS_TABLE}
        INSERT INTO goals ({GOAL_COLUMNS})
            SELECT id, text, weekdays, target_date, created_at, archived_at
            FROM goals_pre_join_ideas;
        INSERT INTO goal_ideas (goal_id, idea_id)
            SELECT id, idea_id FROM goals_pre_join_ideas WHERE idea_id IS NOT NULL;
        DROP TABLE goals_pre_join_ideas;
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
    _ensure_goal_weekdays(conn)
    _ensure_goal_ideas_join_table(conn)
    _migrate_from_v1_daily_goals(conn)
    _ensure_encrypted_content(conn)
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
    idea["text"] = decrypt_str(idea["text"])
    idea["notes"] = decrypt_str(idea["notes"])
    fields_raw = decrypt_str(idea["fields"])
    idea["fields"] = json.loads(fields_raw) if fields_raw else {}
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
            (encrypt_str(text), status, ts, ts, encrypt_str(encode_fields(fields))),
        )
        conn.commit()
        return cur.lastrowid


def get_idea(conn: sqlite3.Connection, idea_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {IDEA_COLUMNS} FROM ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    return row_to_idea(row) if row else None


def update_idea(conn: sqlite3.Connection, idea_id: int, updates: dict) -> dict | None:
    """Update whichever of status/text/notes/fields is a key in `updates`,
    leaving the rest untouched (so `updates={"notes": None}` clears notes,
    while omitting the "notes" key leaves it alone). Centralizing every idea
    write here -- instead of ad-hoc UPDATE statements in server.py/cli/idea
    -- is what guarantees text/notes/fields are always encrypted before they
    hit the database."""
    if get_idea(conn, idea_id) is None:
        return None

    set_clauses, values = ["updated_at = ?"], [now_str()]
    if "status" in updates:
        set_clauses.append("status = ?")
        values.append(updates["status"])
    if "text" in updates:
        set_clauses.append("text = ?")
        values.append(encrypt_str(updates["text"]))
    if "notes" in updates:
        set_clauses.append("notes = ?")
        values.append(encrypt_str(updates["notes"]))
    if "fields" in updates:
        set_clauses.append("fields = ?")
        values.append(encrypt_str(encode_fields(updates["fields"])))

    values.append(idea_id)
    conn.execute(f"UPDATE ideas SET {', '.join(set_clauses)} WHERE id = ?", values)
    conn.commit()
    return get_idea(conn, idea_id)


# ---- goals ----
#
# A goal is its own thing -- its own text, e.g. "walk 10000 steps" -- not a
# tagged idea. It can optionally link to one or more ideas (concrete steps
# toward those longer-term objectives) but doesn't have to -- see the
# goal_ideas join table. A goal is either:
#   - recurring: due on whichever weekday(s) it's set to (Monday=0..Sunday=6),
#     from its created_at date until it's stopped (archived_at set) -- all
#     seven days is a daily habit, one day is a weekly check-in, any other
#     subset is a milestone schedule like "Mon/Wed/Fri"
#   - one-off: due on exactly one target_date, which can be any date at all
# Completion is always self-reported into goal_log, one row per
# (goal_id, date) -- never derived from an idea's status, since most goals
# (the steps-walked example) have no idea, and thus no status, to derive
# from at all.


def today_str() -> str:
    return datetime.now().date().isoformat()


def create_goal(
    conn: sqlite3.Connection,
    text: str,
    idea_ids: list[int] | None = None,
    weekdays: list[int] | None = None,
    target_date: str | None = None,
) -> dict | None:
    """Returns None if any given idea id doesn't exist. A non-empty
    `weekdays` (Monday=0..Sunday=6) makes the goal recurring and ignores
    target_date; otherwise it's one-off, defaulting target_date to today if
    not given."""
    idea_ids = sorted(set(idea_ids)) if idea_ids else []
    for idea_id in idea_ids:
        if get_idea(conn, idea_id) is None:
            return None
    weekdays = sorted(set(weekdays)) if weekdays else None
    if weekdays is None and target_date is None:
        target_date = today_str()
    if weekdays is not None:
        target_date = None
    weekdays_str = ",".join(str(d) for d in weekdays) if weekdays else None

    cur = conn.execute(
        "INSERT INTO goals (text, weekdays, target_date, created_at) VALUES (?, ?, ?, ?)",
        (encrypt_str(text), weekdays_str, target_date, now_str()),
    )
    goal_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO goal_ideas (goal_id, idea_id) VALUES (?, ?)",
        [(goal_id, idea_id) for idea_id in idea_ids],
    )
    conn.commit()
    return get_goal(conn, goal_id)


def _goal_idea_ids(conn: sqlite3.Connection, goal_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT idea_id FROM goal_ideas WHERE goal_id = ? ORDER BY idea_id", (goal_id,)
    ).fetchall()
    return [r["idea_id"] for r in rows]


def _attach_idea_summaries(conn: sqlite3.Connection, goal: dict) -> dict:
    """Resolve a goal's linked idea_ids into {id, text} pairs -- shared by
    every goal listing that displays which idea(s) a goal is linked to."""
    goal["ideas"] = [
        {"id": idea_id, "text": get_idea(conn, idea_id)["text"]}
        for idea_id in goal["idea_ids"]
    ]
    return goal


def row_to_goal(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    goal = dict(row)
    goal["text"] = decrypt_str(goal["text"])
    goal["weekdays"] = (
        [int(d) for d in goal["weekdays"].split(",")] if goal["weekdays"] else None
    )
    goal["idea_ids"] = _goal_idea_ids(conn, goal["id"])
    return goal


def get_goal(conn: sqlite3.Connection, goal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row is None:
        return None
    return _attach_idea_summaries(conn, row_to_goal(conn, row))


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
        "WHERE id = ? AND weekdays IS NOT NULL AND archived_at IS NULL",
        (now_str(), goal_id),
    )
    conn.commit()
    return cur.rowcount > 0


def remove_goal(conn: sqlite3.Connection, goal_id: int) -> bool:
    """Hard-delete a goal definition, its completion history, and its idea
    link(s)."""
    conn.execute("DELETE FROM goal_log WHERE goal_id = ?", (goal_id,))
    conn.execute("DELETE FROM goal_ideas WHERE goal_id = ?", (goal_id,))
    cur = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
    return cur.rowcount > 0


def unlink_goals_from_idea(conn: sqlite3.Connection, idea_id: int) -> None:
    """Called when an idea is deleted: the goal(s) linked to it keep
    existing (and keep their history, and any other idea links they have)
    -- they just lose this one link, since completion was never derived
    from the idea in the first place."""
    conn.execute("DELETE FROM goal_ideas WHERE idea_id = ?", (idea_id,))


def link_goal(conn: sqlite3.Connection, goal_id: int, idea_id: int) -> dict | None:
    """Add a link from this goal to this idea, on top of any links it
    already has -- a goal can link to more than one idea. A no-op if
    already linked. Returns None if the goal or the idea doesn't exist."""
    if get_goal(conn, goal_id) is None or get_idea(conn, idea_id) is None:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO goal_ideas (goal_id, idea_id) VALUES (?, ?)",
        (goal_id, idea_id),
    )
    conn.commit()
    return get_goal(conn, goal_id)


def unlink_goal(conn: sqlite3.Connection, goal_id: int, idea_id: int) -> dict | None:
    """Remove one specific goal-idea link (the goal, its history, and any
    of its other idea links are untouched). Returns None if the goal
    doesn't exist."""
    if get_goal(conn, goal_id) is None:
        return None
    conn.execute(
        "DELETE FROM goal_ideas WHERE goal_id = ? AND idea_id = ?", (goal_id, idea_id)
    )
    conn.commit()
    return get_goal(conn, goal_id)


def goals_due_on(conn: sqlite3.Connection, date: str) -> list[dict]:
    """Every goal due on `date`: recurring goals active that day *and*
    scheduled for that weekday, plus one-off goals targeting it exactly.
    completed_at comes from goal_log if a row exists for that day, else
    NULL (nothing logged = not done). The weekday check happens in Python
    (after decoding `weekdays` via row_to_goal) rather than SQL -- a goal
    whose active window matches but whose weekday doesn't is simply left
    out of the result, same as a goal with nothing due at all, which is
    exactly what compute_streak's day-skipping already expects."""
    rows = conn.execute(
        "SELECT g.*, gl.completed_at AS completed_at "
        "FROM goals g "
        "LEFT JOIN goal_log gl ON gl.goal_id = g.id AND gl.date = ? "
        "WHERE (g.weekdays IS NOT NULL AND date(g.created_at) <= date(?) "
        "       AND (g.archived_at IS NULL OR date(g.archived_at) > date(?))) "
        "   OR (g.weekdays IS NULL AND g.target_date = ?) "
        "ORDER BY g.created_at",
        (date, date, date, date),
    ).fetchall()
    weekday = date_cls.fromisoformat(date).weekday()
    goals = [_attach_idea_summaries(conn, row_to_goal(conn, row)) for row in rows]
    return [g for g in goals if g["weekdays"] is None or weekday in g["weekdays"]]


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
        "  SELECT date(created_at) AS d FROM goals WHERE weekdays IS NOT NULL"
        "  UNION ALL"
        "  SELECT target_date AS d FROM goals WHERE weekdays IS NULL"
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


def _goal_completion_stats(conn: sqlite3.Connection, goal_id: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last "
        "FROM goal_log WHERE goal_id = ? AND completed_at IS NOT NULL",
        (goal_id,),
    ).fetchone()
    return {
        "times_completed": row["n"],
        "first_completed": row["first"],
        "last_completed": row["last"],
    }


def _is_goal_completed(conn: sqlite3.Connection, goal: dict) -> bool:
    """A recurring goal never finishes on its own -- it "completes" only by
    being stopped, regardless of how many/few of its days were logged done.
    A one-off goal completes exactly when its single target_date has a
    logged completion."""
    if goal["weekdays"] is not None:
        return goal["archived_at"] is not None
    row = conn.execute(
        "SELECT 1 FROM goal_log WHERE goal_id = ? AND date = ? AND completed_at IS NOT NULL",
        (goal["id"], goal["target_date"]),
    ).fetchone()
    return row is not None


def _enrich_goal_progress(conn: sqlite3.Connection, goal: dict) -> dict:
    """Attach `completed` and completion-history stats to a goal dict --
    shared by goals_for_idea and completed_goals, the two progress views.
    goal must already carry idea_ids/ideas (i.e. come from row_to_goal +
    _attach_idea_summaries, or get_goal)."""
    goal["completed"] = _is_goal_completed(conn, goal)
    goal.update(_goal_completion_stats(conn, goal["id"]))
    return goal


def goals_for_idea(conn: sqlite3.Connection, idea_id: int) -> list[dict] | None:
    """Every goal linked to one idea, current and completed alike, each
    enriched with progress -- what the idea detail view shows so progress
    made toward it is visible. None if the idea doesn't exist."""
    if get_idea(conn, idea_id) is None:
        return None
    rows = conn.execute(
        "SELECT g.id, g.text, g.weekdays, g.target_date, g.created_at, g.archived_at "
        "FROM goals g JOIN goal_ideas gi ON gi.goal_id = g.id "
        "WHERE gi.idea_id = ? ORDER BY g.created_at",
        (idea_id,),
    ).fetchall()
    return [
        _enrich_goal_progress(
            conn, _attach_idea_summaries(conn, row_to_goal(conn, row))
        )
        for row in rows
    ]


def completed_goals(conn: sqlite3.Connection) -> list[dict]:
    """Every completed goal across the whole database (one-off goals marked
    done, recurring goals that have been stopped) -- the goals screen's
    progress history, most-recently-completed first. Each is enriched like
    goals_for_idea."""
    rows = conn.execute(
        f"SELECT {GOAL_COLUMNS} FROM goals ORDER BY created_at DESC"
    ).fetchall()
    result = []
    for row in rows:
        goal = _enrich_goal_progress(
            conn, _attach_idea_summaries(conn, row_to_goal(conn, row))
        )
        if goal["completed"]:
            result.append(goal)
    result.sort(
        key=lambda g: g["last_completed"] or g["archived_at"] or "", reverse=True
    )
    return result


# ---- goal stats: the stats screen and `idea goal stats` ----
#
# Derived on every call from goals + goal_log -- no stored aggregates that
# could drift. A "goal-day" is one goal being due on one day. Today's
# goal-days only count once they're done, so an unfinished today never drags
# a rate or a streak down (the same rule compute_streak follows).

STATS_RATE_WINDOWS_DAYS = (7, 30, 90)
STATS_HEATMAP_DAYS = 365


@dataclass(frozen=True)
class GoalDay:
    goal_id: int
    day: date_cls
    done: bool


def _days_between(start: date_cls, end: date_cls) -> list[date_cls]:
    """Every day from start to end inclusive; empty if end is before start."""
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def _due_dates_through(goal: dict, today: date_cls) -> list[date_cls]:
    """Every day up to and including `today` that `goal` was due -- the same
    rules goals_due_on applies one day at a time."""
    if goal["weekdays"] is None:
        if goal["target_date"] is None:
            return []
        target = date_cls.fromisoformat(goal["target_date"])
        return [target] if target <= today else []
    start = date_cls.fromisoformat(goal["created_at"][:10])
    end = today
    if goal["archived_at"]:
        stopped_on = date_cls.fromisoformat(goal["archived_at"][:10])
        end = min(end, stopped_on - timedelta(days=1))
    weekdays = set(goal["weekdays"])
    return [d for d in _days_between(start, end) if d.weekday() in weekdays]


def _tracked_dates(
    goal: dict, completed: set[tuple[int, str]], today: date_cls
) -> list[date_cls]:
    """A goal's due days through today, plus any day through today it was
    checked off -- so a check-off made on the day a goal is stopped (which
    makes that day no longer due) still counts. Check-offs dated after
    today don't count yet."""
    last_day = today.isoformat()
    checked_off = {
        date_cls.fromisoformat(day)
        for goal_id, day in completed
        if goal_id == goal["id"] and day <= last_day
    }
    return sorted(set(_due_dates_through(goal, today)) | checked_off)


def _completed_keys(conn: sqlite3.Connection) -> set[tuple[int, str]]:
    rows = conn.execute(
        "SELECT goal_id, date FROM goal_log WHERE completed_at IS NOT NULL"
    ).fetchall()
    return {(r["goal_id"], r["date"]) for r in rows}


def _settled(goal_days: list[GoalDay], today: date_cls) -> list[GoalDay]:
    return [gd for gd in goal_days if gd.done or gd.day < today]


def _rate(goal_days: list[GoalDay]) -> dict:
    done = sum(1 for gd in goal_days if gd.done)
    due = len(goal_days)
    return {"done": done, "due": due, "rate": round(done / due, 4) if due else None}


def _rolling_rates(settled: list[GoalDay], today: date_cls) -> list[dict]:
    rates = []
    for days in STATS_RATE_WINDOWS_DAYS:
        window_start = today - timedelta(days=days - 1)
        in_window = [gd for gd in settled if gd.day >= window_start]
        rates.append({"window": f"{days}d", **_rate(in_window)})
    rates.append({"window": "all", **_rate(settled)})
    return rates


def _weekday_rates(settled: list[GoalDay]) -> list[dict]:
    return [
        {"weekday": weekday, **_rate([gd for gd in settled if gd.day.weekday() == weekday])}
        for weekday in range(7)
    ]


def _group_by_day(goal_days: list[GoalDay]) -> dict[date_cls, list[GoalDay]]:
    by_day = defaultdict(list)
    for gd in goal_days:
        by_day[gd.day].append(gd)
    return by_day


def _heatmap(goal_days: list[GoalDay], today: date_cls) -> list[dict]:
    """One entry per day from the first due day (capped to the last
    STATS_HEATMAP_DAYS) through today, including days with nothing due."""
    if not goal_days:
        return []
    earliest_shown = today - timedelta(days=STATS_HEATMAP_DAYS - 1)
    start = max(min(gd.day for gd in goal_days), earliest_shown)
    by_day = _group_by_day(goal_days)
    return [
        {
            "date": day.isoformat(),
            "done": sum(1 for gd in by_day[day] if gd.done),
            "due": len(by_day[day]),
        }
        for day in _days_between(start, today)
    ]


def _day_totals(goal_days: list[GoalDay], today: date_cls) -> dict:
    """A day is tracked once it's settled (past, or today fully done) and
    perfect when every goal due on it was done."""
    tracked = perfect = 0
    for day, due in _group_by_day(goal_days).items():
        all_done = all(gd.done for gd in due)
        if day < today or all_done:
            tracked += 1
            perfect += all_done
    return {
        "checkoffs": sum(1 for gd in goal_days if gd.done),
        "tracked_days": tracked,
        "perfect_days": perfect,
    }


def _current_and_best_run(settled: list[GoalDay]) -> tuple[int, int]:
    """Consecutive done goal-days ending at the latest settled one, and the
    longest such run ever. `settled` must be one goal's days, oldest first."""
    best = run = 0
    for gd in settled:
        run = run + 1 if gd.done else 0
        best = max(best, run)
    return run, best


def _recurring_goal_stats(goal: dict, own_days: list[GoalDay], today: date_cls) -> dict:
    """A stopped goal has no current streak -- only its best one."""
    settled = _settled(own_days, today)
    streak, best_streak = _current_and_best_run(settled)
    if goal["archived_at"]:
        streak = 0
    done_days = [gd.day for gd in own_days if gd.done]
    return {
        "id": goal["id"],
        "text": goal["text"],
        "weekdays": goal["weekdays"],
        "created_at": goal["created_at"],
        "archived_at": goal["archived_at"],
        **_rate(settled),
        "streak": streak,
        "best_streak": best_streak,
        "last_done": max(done_days).isoformat() if done_days else None,
    }


def _one_off_summary(
    one_offs: list[dict], completed: set[tuple[int, str]], today: date_cls
) -> dict:
    """Pending covers today and later -- a one-off due today isn't missed
    until the day is over. A goal with no target date is never due (see
    goals_due_on), so it's left out."""
    summary = {"done": 0, "missed": 0, "pending": 0}
    for goal in one_offs:
        if goal["target_date"] is None:
            continue
        if (goal["id"], goal["target_date"]) in completed:
            summary["done"] += 1
        elif date_cls.fromisoformat(goal["target_date"]) < today:
            summary["missed"] += 1
        else:
            summary["pending"] += 1
    return summary


def goal_stats(conn: sqlite3.Connection, today: str | None = None) -> dict:
    """Everything the stats screen shows: lifetime totals, rolling and
    per-weekday completion rates, a per-day heatmap, a per-goal breakdown of
    recurring goals (active first, then stopped), and one-off counts. All of
    it runs through `today` -- except one_offs, which also counts goals
    targeting later days (done early or still pending)."""
    today_d = date_cls.fromisoformat(today) if today else date_cls.today()
    rows = conn.execute(f"SELECT {GOAL_COLUMNS} FROM goals ORDER BY created_at").fetchall()
    goals = [row_to_goal(conn, row) for row in rows]
    completed = _completed_keys(conn)

    days_by_goal = {
        goal["id"]: [
            GoalDay(goal["id"], day, (goal["id"], day.isoformat()) in completed)
            for day in _tracked_dates(goal, completed, today_d)
        ]
        for goal in goals
    }
    goal_days = [gd for own_days in days_by_goal.values() for gd in own_days]
    settled = _settled(goal_days, today_d)
    recurring = sorted(
        (g for g in goals if g["weekdays"] is not None),
        key=lambda g: g["archived_at"] is not None,
    )

    return {
        "today": today_d.isoformat(),
        "totals": _day_totals(goal_days, today_d),
        "rates": _rolling_rates(settled, today_d),
        "weekdays": _weekday_rates(settled),
        "heatmap": _heatmap(goal_days, today_d),
        "recurring": [
            _recurring_goal_stats(g, days_by_goal[g["id"]], today_d) for g in recurring
        ],
        "one_offs": _one_off_summary(
            [g for g in goals if g["weekdays"] is None], completed, today_d
        ),
    }
