"""Tests for scripts/expire.py, the 8-week queued -> archive sweep.

Loaded via importlib since it's a script, not a package module. Its
LOG_PATH is monkeypatched to a tmp file so tests never write to the
real data/expire.log.
"""

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import dbutil

EXPIRE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "expire.py"

STALE = (datetime.now() - timedelta(weeks=9)).isoformat(sep=" ", timespec="seconds")


def load_expire_module():
    spec = importlib.util.spec_from_file_location("expire_under_test", EXPIRE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def expire_module(db_path, tmp_path, monkeypatch):
    module = load_expire_module()
    monkeypatch.setattr(module, "LOG_PATH", tmp_path / "expire_test.log")
    return module


def status_of(idea_id):
    conn = dbutil.get_conn()
    idea = dbutil.get_idea(conn, idea_id)
    conn.close()
    return idea["status"]


def test_expires_stale_queued_idea(expire_module):
    idea_id = dbutil.add_idea("stale queued idea", status="queued", created_at=STALE)
    expire_module.main()
    assert status_of(idea_id) == "archive"


def test_does_not_expire_recent_queued_idea(expire_module):
    idea_id = dbutil.add_idea("fresh queued idea", status="queued")
    expire_module.main()
    assert status_of(idea_id) == "queued"


def test_does_not_touch_non_queued_ideas(expire_module):
    idea_id = dbutil.add_idea("stale but active", status="active", created_at=STALE)
    expire_module.main()
    assert status_of(idea_id) == "active"


def test_expiry_bumps_updated_at(expire_module):
    idea_id = dbutil.add_idea("stale", status="queued", created_at=STALE)
    expire_module.main()

    conn = dbutil.get_conn()
    idea = dbutil.get_idea(conn, idea_id)
    conn.close()
    assert idea["updated_at"] != STALE


def test_logs_each_expiry(expire_module):
    dbutil.add_idea("stale", status="queued", created_at=STALE)
    expire_module.main()
    assert "expired idea" in expire_module.LOG_PATH.read_text()


def test_logs_when_nothing_expires(expire_module):
    expire_module.main()
    assert "no ideas expired" in expire_module.LOG_PATH.read_text()
