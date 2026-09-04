import json
import sqlite3

import pytest

import dbutil


def test_get_conn_creates_schema(db_path):
    conn = dbutil.get_conn()
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert {"ideas", "import_log", "flagged_imports"} <= tables


def test_add_idea_defaults_to_inbox(db_path):
    idea_id = dbutil.add_idea("test idea")
    conn = dbutil.get_conn()
    idea = dbutil.get_idea(conn, idea_id)
    conn.close()

    assert idea["text"] == "test idea"
    assert idea["status"] == "inbox"
    assert idea["created_at"] == idea["updated_at"]
    assert idea["fields"] == {}


def test_add_idea_with_status_and_fields(db_path):
    idea_id = dbutil.add_idea(
        "queued idea", status="queued", fields={"priority": "high"}
    )
    conn = dbutil.get_conn()
    idea = dbutil.get_idea(conn, idea_id)
    conn.close()

    assert idea["status"] == "queued"
    assert idea["fields"] == {"priority": "high"}


def test_add_idea_preserves_given_created_at(db_path):
    idea_id = dbutil.add_idea("old idea", created_at="2020-01-01 00:00:00")
    conn = dbutil.get_conn()
    idea = dbutil.get_idea(conn, idea_id)
    conn.close()

    assert idea["created_at"] == "2020-01-01 00:00:00"


def test_get_idea_returns_none_for_missing_id(conn):
    assert dbutil.get_idea(conn, 999) is None


def test_row_to_idea_parses_json_fields(conn):
    conn.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at, fields) "
        "VALUES (?, 'inbox', 'x', 'x', ?)",
        ("t", json.dumps({"a": "b"})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ideas").fetchone()

    assert dbutil.row_to_idea(row)["fields"] == {"a": "b"}


def test_row_to_idea_empty_fields_is_empty_dict_not_none(conn):
    conn.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES ('t', 'inbox', 'x', 'x')"
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ideas").fetchone()

    assert dbutil.row_to_idea(row)["fields"] == {}


def test_encode_fields_none_for_empty_or_none():
    assert dbutil.encode_fields(None) is None
    assert dbutil.encode_fields({}) is None


def test_encode_fields_json_for_nonempty():
    assert json.loads(dbutil.encode_fields({"a": "b"})) == {"a": "b"}


def test_connection_context_manager_closes_on_exception(db_path):
    with pytest.raises(ValueError):
        with dbutil.connection() as c:
            c.execute("SELECT 1")
            raise ValueError("boom")

    # the DB file wasn't left locked/corrupted by the exception
    c2 = dbutil.get_conn()
    c2.execute("SELECT 1")
    c2.close()


def test_ensure_fields_column_migrates_pre_existing_table(db_path):
    """Simulates a DB created before the `fields` column existed."""
    raw = sqlite3.connect(db_path)
    raw.execute("""
        CREATE TABLE ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inbox',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notes TEXT
        )
        """)
    raw.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES ('old row', 'inbox', 'x', 'x')"
    )
    raw.commit()
    raw.close()

    conn = dbutil.get_conn()  # runs the migration check
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
    row = conn.execute("SELECT * FROM ideas WHERE text = 'old row'").fetchone()
    conn.close()

    assert "fields" in columns
    assert dbutil.row_to_idea(row)["fields"] == {}


def test_ensure_fields_column_is_idempotent(db_path):
    # must not raise "duplicate column name" on repeated connections
    dbutil.get_conn().close()
    dbutil.get_conn().close()
    dbutil.get_conn().close()


# ---- _ensure_frontier_status ----


def test_ensure_frontier_status_rebuilds_old_constraint_preserving_rows(db_path):
    """Simulates a DB created before 'frontier' was a valid status."""
    raw = sqlite3.connect(db_path)
    raw.execute("""
        CREATE TABLE ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('inbox','active','queued','horizon','archive')) DEFAULT 'inbox',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notes TEXT,
            fields TEXT
        )
        """)
    raw.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES ('old row', 'horizon', 'x', 'x')"
    )
    raw.commit()
    raw.close()

    conn = dbutil.get_conn()  # runs both migrations
    row = conn.execute("SELECT * FROM ideas WHERE text = 'old row'").fetchone()
    assert row["status"] == "horizon"

    # the new status is now actually accepted (would raise IntegrityError otherwise)
    conn.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES ('new row', 'frontier', 'x', 'x')"
    )
    conn.commit()
    conn.close()


def test_ensure_frontier_status_is_idempotent(db_path):
    dbutil.get_conn().close()
    dbutil.get_conn().close()
    dbutil.add_idea("x", status="frontier")  # would raise if the CHECK weren't widened


# ---- daily goals ----


def test_add_goal_snapshots_text_and_status(conn):
    idea_id = dbutil.add_idea("ship it", status="active")
    goal = dbutil.add_goal(conn, idea_id, "2026-09-04")

    assert goal["idea_id"] == idea_id
    assert goal["idea_text_snapshot"] == "ship it"
    assert goal["status_at_tag"] == "active"
    assert goal["completed_at"] is None


def test_add_goal_missing_idea_returns_none(conn):
    assert dbutil.add_goal(conn, 9999, "2026-09-04") is None


def test_add_goal_retagging_is_a_noop(conn):
    idea_id = dbutil.add_idea("x")
    first = dbutil.add_goal(conn, idea_id, "2026-09-04")
    second = dbutil.add_goal(conn, idea_id, "2026-09-04")

    assert first["id"] == second["id"]
    assert len(dbutil.goals_for_date(conn, "2026-09-04")) == 1


def test_remove_goal(conn):
    idea_id = dbutil.add_idea("x")
    dbutil.add_goal(conn, idea_id, "2026-09-04")

    assert dbutil.remove_goal(conn, idea_id, "2026-09-04") is True
    assert dbutil.goals_for_date(conn, "2026-09-04") == []


def test_remove_goal_not_tagged_returns_false(conn):
    idea_id = dbutil.add_idea("x")
    assert dbutil.remove_goal(conn, idea_id, "2026-09-04") is False


def test_remove_goals_for_idea(conn):
    idea_id = dbutil.add_idea("x")
    dbutil.add_goal(conn, idea_id, "2026-09-04")
    dbutil.remove_goals_for_idea(conn, idea_id)
    conn.commit()

    assert dbutil.goals_for_date(conn, "2026-09-04") == []


def test_sync_goal_completion_flips_only_on_real_status_change(conn):
    idea_id = dbutil.add_idea("x", status="inbox")
    dbutil.add_goal(conn, idea_id, "2026-09-04")

    goals = dbutil.goals_for_date(conn, "2026-09-04")  # syncs internally
    assert goals[0]["completed_at"] is None

    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (idea_id,))
    conn.commit()

    goals = dbutil.goals_for_date(conn, "2026-09-04")
    assert goals[0]["completed_at"] is not None


def test_sync_goal_completion_is_sticky(conn):
    """Moving the idea back to its original status doesn't un-win the goal."""
    idea_id = dbutil.add_idea("x", status="inbox")
    dbutil.add_goal(conn, idea_id, "2026-09-04")
    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (idea_id,))
    conn.commit()
    dbutil.goals_for_date(conn, "2026-09-04")  # sync
    completed_at = dbutil.goals_for_date(conn, "2026-09-04")[0]["completed_at"]

    conn.execute("UPDATE ideas SET status = 'inbox' WHERE id = ?", (idea_id,))
    conn.commit()

    goals = dbutil.goals_for_date(conn, "2026-09-04")
    assert goals[0]["completed_at"] == completed_at


def test_completed_dates_requires_all_goals_done(conn):
    a = dbutil.add_idea("a", status="inbox")
    b = dbutil.add_idea("b", status="inbox")
    dbutil.add_goal(conn, a, "2026-09-04")
    dbutil.add_goal(conn, b, "2026-09-04")
    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (a,))
    conn.commit()

    assert dbutil.completed_dates(conn) == set()  # b still pending

    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (b,))
    conn.commit()

    assert dbutil.completed_dates(conn) == {"2026-09-04"}


def test_compute_streak_counts_consecutive_complete_days(conn):
    dates = ["2026-09-01", "2026-09-02", "2026-09-03"]
    # create every idea first: dbutil.add_idea() opens its own connection,
    # which would deadlock against `conn`'s open write transaction if
    # interleaved with the updates below
    idea_ids = {
        date: dbutil.add_idea(f"idea for {date}", status="inbox") for date in dates
    }

    for date in dates:
        dbutil.add_goal(conn, idea_ids[date], date)
        conn.execute(
            "UPDATE ideas SET status = 'active' WHERE id = ?", (idea_ids[date],)
        )
    conn.commit()

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["streak"] == 3
    assert info["today_total"] == 0
    assert info["today_complete"] is False  # no goals today; doesn't break the streak


def test_compute_streak_unfinished_today_does_not_break_streak(conn):
    idea_id = dbutil.add_idea("yesterday", status="inbox")
    dbutil.add_goal(conn, idea_id, "2026-09-03")
    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (idea_id,))
    conn.commit()

    today_idea = dbutil.add_idea("today", status="inbox")
    dbutil.add_goal(conn, today_idea, "2026-09-04")  # tagged, not yet advanced

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["streak"] == 1
    assert info["today_complete"] is False
    assert info["today_done"] == 0
    assert info["today_total"] == 1


def test_compute_streak_breaks_on_a_gap(conn):
    idea_id = dbutil.add_idea("two days ago", status="inbox")
    dbutil.add_goal(conn, idea_id, "2026-09-02")
    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (idea_id,))
    conn.commit()
    # 2026-09-03 has no goals at all -- gap before today

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["streak"] == 0


def test_total_xp_counts_completions_only(conn):
    a = dbutil.add_idea("a", status="inbox")
    b = dbutil.add_idea("b", status="inbox")
    dbutil.add_goal(conn, a, "2026-09-04")
    dbutil.add_goal(conn, b, "2026-09-04")
    conn.execute("UPDATE ideas SET status = 'active' WHERE id = ?", (a,))
    conn.commit()

    assert dbutil.total_xp(conn) == 1
