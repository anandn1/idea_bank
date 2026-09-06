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
    cur = raw.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES ('old row', 'inbox', 'x', 'x')"
    )
    old_row_id = cur.lastrowid
    raw.commit()
    raw.close()

    conn = dbutil.get_conn()  # runs the migration check (and encrypts 'old row')
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (old_row_id,)).fetchone()
    conn.close()

    assert "fields" in columns
    assert dbutil.row_to_idea(row)["fields"] == {}


def test_ensure_fields_column_is_idempotent(db_path):
    # must not raise "duplicate column name" on repeated connections
    dbutil.get_conn().close()
    dbutil.get_conn().close()
    dbutil.get_conn().close()


# ---- privacy: encryption at rest ----


def test_encrypt_str_round_trips(db_path):
    assert dbutil.decrypt_str(dbutil.encrypt_str("a secret idea")) == "a secret idea"


def test_encrypt_str_passes_none_through(db_path):
    assert dbutil.encrypt_str(None) is None
    assert dbutil.decrypt_str(None) is None


def test_decrypt_str_passes_plaintext_through_unchanged(db_path):
    """A value with no ENC_PREFIX (not yet migrated, or written directly by
    test setup code) is returned as-is rather than raising."""
    assert dbutil.decrypt_str("plain, un-prefixed text") == "plain, un-prefixed text"


def test_add_idea_stores_ciphertext_not_plaintext(db_path):
    idea_id = dbutil.add_idea("a very private idea", fields={"secret": "yes"})
    raw = sqlite3.connect(db_path)
    row = raw.execute(
        "SELECT text, fields FROM ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    raw.close()

    assert "a very private idea" not in row[0]
    assert row[0].startswith(dbutil.ENC_PREFIX)
    assert "secret" not in row[1]


def test_create_goal_stores_ciphertext_not_plaintext(conn):
    goal = dbutil.create_goal(conn, "a private habit")
    row = conn.execute("SELECT text FROM goals WHERE id = ?", (goal["id"],)).fetchone()

    assert "a private habit" not in row["text"]
    assert row["text"].startswith(dbutil.ENC_PREFIX)


def test_ensure_encrypted_content_migrates_legacy_plaintext_rows(db_path):
    raw = sqlite3.connect(db_path)
    raw.execute(
        "CREATE TABLE ideas (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'inbox', created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, notes TEXT, fields TEXT)"
    )
    cur = raw.execute(
        "INSERT INTO ideas (text, created_at, updated_at) VALUES ('legacy idea', 'x', 'x')"
    )
    legacy_id = cur.lastrowid
    raw.commit()
    raw.close()

    conn = dbutil.get_conn()  # runs _ensure_encrypted_content
    idea = dbutil.get_idea(conn, legacy_id)
    raw_row = conn.execute(
        "SELECT text FROM ideas WHERE id = ?", (legacy_id,)
    ).fetchone()
    conn.close()

    assert idea["text"] == "legacy idea"  # still reads back correctly
    assert raw_row["text"].startswith(dbutil.ENC_PREFIX)  # but is now encrypted at rest


def test_ensure_encrypted_content_is_idempotent(db_path):
    dbutil.add_idea("x")
    dbutil.get_conn().close()
    dbutil.get_conn().close()  # must not double-encrypt an already-encrypted row

    conn = dbutil.get_conn()
    idea = dbutil.get_idea(conn, 1)
    conn.close()
    assert idea["text"] == "x"


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
    cur = raw.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES ('old row', 'horizon', 'x', 'x')"
    )
    old_row_id = cur.lastrowid
    raw.commit()
    raw.close()

    conn = dbutil.get_conn()  # runs both migrations
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (old_row_id,)).fetchone()
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


# ---- _ensure_goal_weekdays ----


def test_ensure_goal_weekdays_rebuilds_old_recurring_column(db_path):
    """Simulates a DB created before weekday-set recurrence existed."""
    raw = sqlite3.connect(db_path)
    raw.execute("""
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            idea_id INTEGER,
            recurring INTEGER NOT NULL DEFAULT 0,
            target_date TEXT,
            created_at TEXT NOT NULL,
            archived_at TEXT
        )
        """)
    cur_recurring = raw.execute(
        "INSERT INTO goals (text, recurring, created_at) VALUES ('old daily', 1, 'x')"
    )
    recurring_id = cur_recurring.lastrowid
    cur_one_off = raw.execute(
        "INSERT INTO goals (text, recurring, target_date, created_at) "
        "VALUES ('old one-off', 0, '2026-09-05', 'x')"
    )
    one_off_id = cur_one_off.lastrowid
    raw.commit()
    raw.close()

    conn = dbutil.get_conn()  # runs the migration
    recurring_row = dbutil.get_goal(conn, recurring_id)
    one_off_row = dbutil.get_goal(conn, one_off_id)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(goals)")}
    conn.close()

    assert "recurring" not in columns
    assert "weekdays" in columns
    assert recurring_row["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert recurring_row["target_date"] is None
    assert one_off_row["weekdays"] is None
    assert one_off_row["target_date"] == "2026-09-05"


def test_ensure_goal_weekdays_is_idempotent(db_path):
    dbutil.get_conn().close()
    dbutil.get_conn().close()
    dbutil.get_conn().close()


# ---- goals ----
#
# A goal is its own thing (own text), optionally linked to an idea, always
# self-reported as done -- never derived from an idea's status. Recurrence
# is a weekday set (Monday=0..Sunday=6), not a boolean -- daily is just all
# seven days.


def _insert_recurring_goal(conn, text, created_at_date, weekdays="0,1,2,3,4,5,6"):
    """Backdate a goal's created_at so streak tests can control which days
    it's due on, instead of racing the real current date. Defaults to daily
    so every existing call site keeps its current behavior."""
    conn.execute(
        "INSERT INTO goals (text, weekdays, created_at) VALUES (?, ?, ?)",
        (text, weekdays, f"{created_at_date} 08:00:00"),
    )
    conn.commit()
    return conn.execute("SELECT id FROM goals WHERE text = ?", (text,)).fetchone()["id"]


def test_create_goal_one_off_defaults_target_date_to_today(conn):
    goal = dbutil.create_goal(conn, "x")
    assert goal["target_date"] == dbutil.today_str()
    assert goal["weekdays"] is None
    assert goal["idea_id"] is None


def test_create_goal_weekdays_ignores_target_date(conn):
    goal = dbutil.create_goal(
        conn, "x", weekdays=[0, 1, 2, 3, 4, 5, 6], target_date="2026-09-05"
    )
    assert goal["target_date"] is None
    assert goal["weekdays"] == [0, 1, 2, 3, 4, 5, 6]


def test_create_goal_weekdays_deduped_and_sorted(conn):
    goal = dbutil.create_goal(conn, "x", weekdays=[4, 0, 2, 0])
    assert goal["weekdays"] == [0, 2, 4]


def test_create_goal_empty_weekdays_list_is_one_off(conn):
    goal = dbutil.create_goal(conn, "x", weekdays=[])
    assert goal["weekdays"] is None
    assert goal["target_date"] == dbutil.today_str()


def test_create_goal_with_idea_link(conn):
    idea_id = dbutil.add_idea("run every day")
    goal = dbutil.create_goal(conn, "walk 10000 steps", idea_id=idea_id, weekdays=[0])
    assert goal["idea_id"] == idea_id


def test_create_goal_missing_idea_returns_none(conn):
    assert dbutil.create_goal(conn, "x", idea_id=9999) is None


def test_missing_goal_ids(conn):
    goal = dbutil.create_goal(conn, "x")
    assert dbutil.missing_goal_ids(conn, [goal["id"], 9999]) == [9999]


def test_goals_due_on_recurring_due_every_day_since_creation(conn):
    _insert_recurring_goal(conn, "walk", "2026-09-01")
    assert dbutil.goals_due_on(conn, "2026-08-31") == []  # before creation
    assert len(dbutil.goals_due_on(conn, "2026-09-01")) == 1
    assert len(dbutil.goals_due_on(conn, "2026-09-10")) == 1


def test_goals_due_on_weekday_set_only_matches_those_weekdays(conn):
    # 2026-09-01 is a Tuesday, 2026-09-07 is a Monday
    _insert_recurring_goal(conn, "monday workout", "2026-09-01", weekdays="0")
    assert dbutil.goals_due_on(conn, "2026-09-01") == []  # Tuesday -- not due
    due = dbutil.goals_due_on(conn, "2026-09-07")  # Monday -- due
    assert len(due) == 1
    assert due[0]["weekdays"] == [0]


def test_goals_due_on_one_off_only_on_target_date(conn):
    goal = dbutil.create_goal(conn, "draft the proposal", target_date="2026-09-05")
    assert dbutil.goals_due_on(conn, "2026-09-04") == []
    due = dbutil.goals_due_on(conn, "2026-09-05")
    assert len(due) == 1
    assert due[0]["id"] == goal["id"]


def test_set_goal_done_toggle(conn):
    goal = dbutil.create_goal(conn, "x")
    date = goal["target_date"]

    done = dbutil.set_goal_done(conn, goal["id"], date, True)
    assert done["completed_at"] is not None

    undone = dbutil.set_goal_done(conn, goal["id"], date, False)
    assert undone["completed_at"] is None


def test_set_goal_done_not_due_returns_none(conn):
    goal = dbutil.create_goal(conn, "x", target_date="2026-09-05")
    assert dbutil.set_goal_done(conn, goal["id"], "2026-09-01", True) is None


def test_set_goal_done_missing_goal_returns_none(conn):
    assert dbutil.set_goal_done(conn, 9999, "2026-09-04", True) is None


def test_stop_goal_only_works_on_recurring(conn):
    one_off = dbutil.create_goal(conn, "x")
    assert dbutil.stop_goal(conn, one_off["id"]) is False

    recurring = dbutil.create_goal(conn, "y", weekdays=[0, 1, 2, 3, 4, 5, 6])
    assert dbutil.stop_goal(conn, recurring["id"]) is True
    assert dbutil.stop_goal(conn, recurring["id"]) is False  # already stopped


def test_stop_goal_removes_it_from_current_and_future_dates(conn):
    goal = dbutil.create_goal(conn, "walk", weekdays=[0, 1, 2, 3, 4, 5, 6])
    today = dbutil.today_str()
    assert len(dbutil.goals_due_on(conn, today)) == 1

    dbutil.stop_goal(conn, goal["id"])
    assert dbutil.goals_due_on(conn, today) == []


def test_remove_goal_deletes_definition_and_history(conn):
    goal = dbutil.create_goal(conn, "x")
    dbutil.set_goal_done(conn, goal["id"], goal["target_date"], True)

    assert dbutil.remove_goal(conn, goal["id"]) is True
    assert dbutil.get_goal(conn, goal["id"]) is None
    assert dbutil.goals_due_on(conn, goal["target_date"]) == []


def test_remove_goal_missing_returns_false(conn):
    assert dbutil.remove_goal(conn, 9999) is False


def test_unlink_goals_from_idea(conn):
    idea_id = dbutil.add_idea("run every day")
    goal = dbutil.create_goal(conn, "walk 10000 steps", idea_id=idea_id)

    dbutil.unlink_goals_from_idea(conn, idea_id)
    conn.commit()

    refreshed = dbutil.get_goal(conn, goal["id"])
    assert refreshed is not None
    assert refreshed["idea_id"] is None


def test_link_goal_sets_idea_id(conn):
    goal = dbutil.create_goal(conn, "walk 10000 steps")  # no idea yet
    idea_id = dbutil.add_idea("run every day")

    linked = dbutil.link_goal(conn, goal["id"], idea_id)
    assert linked["idea_id"] == idea_id


def test_link_goal_can_change_an_existing_link(conn):
    idea_a = dbutil.add_idea("idea a")
    idea_b = dbutil.add_idea("idea b")
    goal = dbutil.create_goal(conn, "x", idea_id=idea_a)

    linked = dbutil.link_goal(conn, goal["id"], idea_b)
    assert linked["idea_id"] == idea_b


def test_link_goal_missing_goal_returns_none(conn):
    idea_id = dbutil.add_idea("x")
    assert dbutil.link_goal(conn, 9999, idea_id) is None


def test_link_goal_missing_idea_returns_none(conn):
    goal = dbutil.create_goal(conn, "x")
    assert dbutil.link_goal(conn, goal["id"], 9999) is None


def test_unlink_goal_clears_idea_id(conn):
    idea_id = dbutil.add_idea("run every day")
    goal = dbutil.create_goal(conn, "x", idea_id=idea_id)

    unlinked = dbutil.unlink_goal(conn, goal["id"])
    assert unlinked["idea_id"] is None


def test_unlink_goal_missing_returns_none(conn):
    assert dbutil.unlink_goal(conn, 9999) is None


def test_compute_streak_counts_consecutive_complete_days(conn):
    goal_id = _insert_recurring_goal(conn, "walk 10000 steps", "2026-09-01")
    for date in ["2026-09-01", "2026-09-02", "2026-09-03"]:
        dbutil.set_goal_done(conn, goal_id, date, True)

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["streak"] == 3
    assert info["today_total"] == 1  # the habit is still due today
    assert info["today_complete"] is False  # ...just not done yet


def test_compute_streak_unfinished_today_does_not_break_streak(conn):
    goal_id = _insert_recurring_goal(conn, "walk", "2026-09-01")
    for date in ["2026-09-01", "2026-09-02", "2026-09-03"]:
        dbutil.set_goal_done(conn, goal_id, date, True)
    # today (2026-09-04) intentionally left undone

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["streak"] == 3
    assert info["today_complete"] is False
    assert info["today_done"] == 0
    assert info["today_total"] == 1


def test_compute_streak_breaks_on_a_missed_due_day(conn):
    goal_id = _insert_recurring_goal(conn, "walk", "2026-09-01")
    dbutil.set_goal_done(conn, goal_id, "2026-09-01", True)
    # 2026-09-02 due but never marked done -- breaks the streak
    dbutil.set_goal_done(conn, goal_id, "2026-09-03", True)

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["streak"] == 1  # only yesterday (09-03) counts


def test_compute_streak_skips_days_with_nothing_due(conn):
    goal_id = _insert_recurring_goal(conn, "walk", "2026-09-01")
    dbutil.set_goal_done(conn, goal_id, "2026-09-01", True)
    # stop it right after -- 09-02 onward has nothing due at all, so those
    # days are skipped, not treated as a break
    conn.execute(
        "UPDATE goals SET archived_at = ? WHERE id = ?",
        ("2026-09-02 00:00:00", goal_id),
    )
    conn.commit()

    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info["today_total"] == 0
    assert info["streak"] == 1


def test_compute_streak_no_goals_ever(conn):
    info = dbutil.compute_streak(conn, today="2026-09-04")
    assert info == {
        "streak": 0,
        "longest": 0,
        "today_complete": False,
        "today_done": 0,
        "today_total": 0,
    }


def test_compute_streak_longest_survives_a_break(conn):
    goal_id = _insert_recurring_goal(conn, "walk", "2026-09-01")
    for date in ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"]:
        dbutil.set_goal_done(conn, goal_id, date, True)
    # 2026-09-06 due but missed -- breaks the run
    dbutil.set_goal_done(conn, goal_id, "2026-09-07", True)

    info = dbutil.compute_streak(conn, today="2026-09-07")
    assert info["streak"] == 1
    assert info["longest"] == 5


def test_compute_streak_weekday_gaps_are_skipped_not_broken(conn):
    # Mondays only: 2026-09-07 and 2026-09-14 are Mondays; every day between
    # them has nothing due (not Monday), which must be skipped, not a break.
    goal_id = _insert_recurring_goal(conn, "monday workout", "2026-09-01", weekdays="0")
    dbutil.set_goal_done(conn, goal_id, "2026-09-07", True)
    dbutil.set_goal_done(conn, goal_id, "2026-09-14", True)

    info = dbutil.compute_streak(conn, today="2026-09-14")
    assert info["streak"] == 2
    assert info["today_total"] == 1
    assert info["today_complete"] is True


def test_compute_streak_weekday_goal_breaks_on_missed_weekday(conn):
    goal_id = _insert_recurring_goal(conn, "monday workout", "2026-09-01", weekdays="0")
    # 2026-09-07 (a Monday) is due but never marked done
    dbutil.set_goal_done(conn, goal_id, "2026-09-14", True)  # the next Monday

    info = dbutil.compute_streak(conn, today="2026-09-14")
    assert info["streak"] == 1  # only today's Monday counts -- last Monday was missed


def test_total_xp_counts_completed_goal_days(conn):
    goal_id = _insert_recurring_goal(conn, "walk", "2026-09-01")
    dbutil.set_goal_done(conn, goal_id, "2026-09-01", True)
    dbutil.set_goal_done(conn, goal_id, "2026-09-02", True)

    assert dbutil.total_xp(conn) == 2
