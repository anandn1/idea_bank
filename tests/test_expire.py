"""Tests for scripts/expire.py, the 8-week queued -> archive sweep.

Loaded via importlib since it's a script, not a package module. Its
LOG_PATH is monkeypatched to a tmp file so tests never write to the
real data/expire.log.
"""

import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import dbutil
from conftest import FIXED_TODAY

EXPIRE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "expire.py"

STALE = (
    datetime.combine(date.fromisoformat(FIXED_TODAY), datetime.min.time()) - timedelta(weeks=9)
).isoformat(sep=" ", timespec="seconds")


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
    assert idea["updated_at"].startswith(f"{FIXED_TODAY} ")


def test_logs_each_expiry(expire_module):
    idea_id = dbutil.add_idea("stale", status="queued", created_at=STALE)
    expire_module.main()
    log = expire_module.LOG_PATH.read_text()
    assert log.startswith(f"{FIXED_TODAY} ")
    assert f"expired idea #{idea_id} " in log
    assert "no ideas expired" not in log


def test_logs_when_nothing_expires(expire_module):
    expire_module.main()
    assert "no ideas expired" in expire_module.LOG_PATH.read_text()


def test_expiry_is_recorded_in_the_status_history(expire_module):
    idea_id = dbutil.add_idea("stale queued idea", status="queued", created_at=STALE)
    expire_module.main()

    conn = dbutil.get_conn()
    rows = conn.execute(
        "SELECT from_status, to_status FROM idea_events WHERE idea_id = ?", (idea_id,)
    ).fetchall()
    conn.close()
    assert [tuple(r) for r in rows] == [("queued", "archive")]


def test_expiry_log_names_the_idea_by_id_never_by_text(expire_module):
    idea_id = dbutil.add_idea("secret plan", status="queued", created_at=STALE)
    expire_module.main()

    log = expire_module.LOG_PATH.read_text()
    assert f"expired idea #{idea_id} (queued since {STALE})" in log
    assert "secret plan" not in log
    assert dbutil.ENC_PREFIX not in log


def _timestamp(moment):
    return moment.isoformat(sep=" ", timespec="seconds")


def test_expiry_boundary_is_exactly_eight_weeks(expire_module, monkeypatch):
    frozen_now = datetime(2026, 9, 10, 12, 0, 0)
    monkeypatch.setattr(dbutil, "now", lambda: frozen_now)
    just_over = dbutil.add_idea(
        "just over", status="queued", created_at=_timestamp(frozen_now - timedelta(weeks=8, seconds=1))
    )
    exactly = dbutil.add_idea(
        "exactly 8 weeks", status="queued", created_at=_timestamp(frozen_now - timedelta(weeks=8))
    )

    expire_module.main()

    assert status_of(just_over) == "archive"
    assert status_of(exactly) == "queued"


def test_expiry_measures_age_from_the_pinned_date(expire_module, monkeypatch):
    # by the real clock (any day this suite runs) this idea is years old;
    # by the pinned date it's only 4.5 weeks old, so it must stay queued
    monkeypatch.setenv("IDEA_BANK_TODAY", "2020-01-01")
    idea_id = dbutil.add_idea("recent", status="queued", created_at="2019-11-30 12:00:00")

    expire_module.main()

    assert status_of(idea_id) == "queued"



def test_unreadable_updated_at_is_skipped_not_fatal(expire_module):
    garbled = dbutil.add_idea("garbled", status="queued", created_at="not a date")
    stale = dbutil.add_idea("stale", status="queued", created_at=STALE)

    expire_module.main()

    assert status_of(garbled) == "queued"
    assert status_of(stale) == "archive"
