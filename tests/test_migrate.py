"""Tests for scripts/migrate.py, the read-only importer from ~/ideas/inbox.md.

CRITICAL isolation requirement: migrate.py's OLD_INBOX defaults to the
real ~/ideas/inbox.md. Every test here monkeypatches OLD_INBOX to a
throwaway tmp_path file before calling main() -- none of them may ever
be allowed to touch the real file.
"""

import importlib.util
from pathlib import Path

import pytest

import dbutil

MIGRATE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "migrate.py"


def load_migrate_module():
    spec = importlib.util.spec_from_file_location("migrate_under_test", MIGRATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrate_module(db_path, tmp_path, monkeypatch):
    module = load_migrate_module()
    monkeypatch.setattr(module, "OLD_INBOX", tmp_path / "fake_inbox.md")
    return module


def write_inbox(module, content):
    module.OLD_INBOX.write_text(content)


def all_ideas():
    conn = dbutil.get_conn()
    rows = [
        dict(row) for row in conn.execute("SELECT text, status, created_at FROM ideas")
    ]
    conn.close()
    return rows


def flagged_reasons():
    conn = dbutil.get_conn()
    reasons = [
        row["reason"] for row in conn.execute("SELECT reason FROM flagged_imports")
    ]
    conn.close()
    return reasons


def test_imports_well_formed_lines(migrate_module):
    write_inbox(
        migrate_module, "2026-01-01 10:00 a real idea\n2026-01-02 11:00 another idea\n"
    )
    migrate_module.main()

    ideas = all_ideas()
    assert {i["text"] for i in ideas} == {"a real idea", "another idea"}
    assert all(i["status"] == "inbox" for i in ideas)


def test_preserves_original_timestamp(migrate_module):
    write_inbox(migrate_module, "2026-01-01 10:00 timed idea\n")
    migrate_module.main()

    idea = next(i for i in all_ideas() if i["text"] == "timed idea")
    assert idea["created_at"] == "2026-01-01 10:00:00"


def test_flags_blank_capture_instead_of_importing(migrate_module):
    write_inbox(migrate_module, "2026-01-01 10:00 \n")
    migrate_module.main()

    assert all_ideas() == []
    reasons = flagged_reasons()
    assert len(reasons) == 1
    assert "blank" in reasons[0]


def test_flags_shell_history_capture(migrate_module):
    write_inbox(
        migrate_module, "2026-01-01 10:00 test entry/home/x/.zsh_history:cat foo\n"
    )
    migrate_module.main()

    assert all_ideas() == []
    reasons = flagged_reasons()
    assert len(reasons) == 1
    assert "shell output" in reasons[0]


def test_flags_malformed_line(migrate_module):
    write_inbox(migrate_module, "not a valid line at all\n")
    migrate_module.main()

    reasons = flagged_reasons()
    assert len(reasons) == 1
    assert "format" in reasons[0]


def test_rerun_is_idempotent(migrate_module):
    write_inbox(migrate_module, "2026-01-01 10:00 idea one\n")
    migrate_module.main()
    migrate_module.main()  # re-run, no new lines

    assert len(all_ideas()) == 1


def test_rerun_picks_up_new_lines_only(migrate_module):
    write_inbox(migrate_module, "2026-01-01 10:00 idea one\n")
    migrate_module.main()
    write_inbox(
        migrate_module,
        "2026-01-01 10:00 idea one\n2026-01-02 11:00 idea two\n",
    )
    migrate_module.main()

    assert {i["text"] for i in all_ideas()} == {"idea one", "idea two"}


def test_duplicate_identical_lines_in_same_file_dont_crash(migrate_module):
    """Regression test: two byte-identical corrupted lines in one file
    must not violate the import_log UNIQUE constraint (the exact bug
    hit during development when inbox.md had two identical
    zsh_history-capture lines)."""
    write_inbox(
        migrate_module,
        "2026-01-01 10:00 test entry/x/.zsh_history:cat foo\n"
        "2026-01-01 10:00 test entry/x/.zsh_history:cat foo\n",
    )
    migrate_module.main()  # must not raise

    assert len(flagged_reasons()) == 1


def test_missing_inbox_file_does_not_crash(migrate_module, capsys):
    migrate_module.main()
    assert "nothing to migrate" in capsys.readouterr().out
    assert all_ideas() == []
