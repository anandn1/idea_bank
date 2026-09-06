"""Shared fixtures. Every fixture here guarantees test isolation from the
real ~/idea_bank/data/ideas.db and the real ~/ideas/ system -- no test in
this suite should ever be able to touch either.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import dbutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = PROJECT_ROOT / "cli" / "idea"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Point dbutil at a fresh, isolated SQLite file (and encryption key)
    for one test -- never the real database or the real ~/.config secret."""
    path = tmp_path / "test_ideas.db"
    monkeypatch.setattr(dbutil, "DB_PATH", path)
    monkeypatch.setattr(dbutil, "KEY_PATH", tmp_path / "test_secret.key")
    return path


@pytest.fixture
def conn(db_path):
    """An open connection to the isolated test DB, closed after the test."""
    connection = dbutil.get_conn()
    yield connection
    connection.close()


@pytest.fixture
def run_cli(tmp_path):
    """Invoke the real `idea` CLI as a subprocess against an isolated DB
    (via the IDEA_BANK_DB_PATH env var dbutil.py reads), so these tests
    exercise the exact contract a human or an agent would see.
    """
    cli_db_path = tmp_path / "cli_test.db"
    cli_key_path = tmp_path / "cli_test_secret.key"

    def _run(*args, input=None):
        env = {
            **os.environ,
            "IDEA_BANK_DB_PATH": str(cli_db_path),
            "IDEA_BANK_KEY_PATH": str(cli_key_path),
        }
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            capture_output=True,
            text=True,
            env=env,
            input=input,
        )

    return _run
