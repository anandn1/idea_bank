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
