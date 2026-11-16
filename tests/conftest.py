"""Shared fixtures. Every fixture here guarantees test isolation from the
real ~/idea_bank/data/ideas.db and the real ~/ideas/ system -- no test in
this suite should ever be able to touch either.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

import dbutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = PROJECT_ROOT / "cli" / "idea"

# The date every test sees as "today" (a Thursday), so date-dependent
# results never vary with the day the suite runs or a run crossing midnight.
FIXED_TODAY = "2026-09-10"


@pytest.fixture
def fixed_today():
    return FIXED_TODAY


@pytest.fixture(autouse=True)
def pin_today(monkeypatch):
    """Every in-process test sees FIXED_TODAY unless it unsets the pin."""
    monkeypatch.setenv("IDEA_BANK_TODAY", FIXED_TODAY)


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
def cli_db_path(tmp_path):
    """The database run_cli's CLI invocations use."""
    return tmp_path / "cli_test.db"


@pytest.fixture
def run_cli(tmp_path, cli_db_path):
    """Invoke the real `idea` CLI as a subprocess against an isolated DB
    (via the IDEA_BANK_DB_PATH env var dbutil.py reads) on FIXED_TODAY, so
    these tests exercise the exact contract a human or an agent would see.
    """
    cli_key_path = tmp_path / "cli_test_secret.key"

    def _run(*args, input=None):
        env = {
            **os.environ,
            "IDEA_BANK_DB_PATH": str(cli_db_path),
            "IDEA_BANK_KEY_PATH": str(cli_key_path),
            "IDEA_BANK_TODAY": FIXED_TODAY,
        }
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            capture_output=True,
            text=True,
            env=env,
            input=input,
        )

    return _run


# ---- browser tests (test_gui_*.py) ----
#
# A real Flask server on a free port with its own temp DB/key, and headless
# Chromium via Playwright. Every browser test is skipped when Playwright or
# its browser isn't installed.

GUI_SERVER_START_TIMEOUT_S = 15


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_serving(url: str, server: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + GUI_SERVER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"test server exited: {log_path.read_text()}")
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("test server didn't start in time")


@pytest.fixture(scope="session")
def gui_db_path(tmp_path_factory):
    """The browser-test server's database, for setting up states the API
    can't create directly (backdated goals, legacy rows)."""
    return tmp_path_factory.mktemp("gui") / "gui_test.db"


@pytest.fixture(scope="session")
def base_url(gui_db_path):
    port = _free_port()
    env = {
        **os.environ,
        "IDEA_BANK_DB_PATH": str(gui_db_path),
        "IDEA_BANK_KEY_PATH": str(gui_db_path.with_name("gui_test_secret.key")),
        "IDEA_BANK_TODAY": FIXED_TODAY,  # the browser's own clock stays real
    }
    # The server logs every request to stderr. Send that to a file: an
    # unread pipe fills up after a few hundred requests and the server then
    # blocks mid-write, hanging whichever test is running.
    log_path = gui_db_path.with_name("gui_server.log")
    with open(log_path, "w") as log:
        server = subprocess.Popen(
            [sys.executable, "-c", f"import server; server.app.run(host='127.0.0.1', port={port})"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_serving(url + "/api/ideas", server, log_path)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=5)


BROWSER_SETUP = (
    "install it with `uv pip install -r requirements-dev.txt` and "
    "`.venv/bin/playwright install --only-shell chromium`, "
    "or run pytest with --skip-browser-tests"
)


def pytest_addoption(parser):
    parser.addoption(
        "--skip-browser-tests",
        action="store_true",
        help="skip the Playwright browser tests (they include the notes sanitizer's security tests)",
    )


# The browser tests hold the notes sanitizer's security tests, so a missing
# browser fails the run rather than quietly skipping them; skipping takes
# an explicit --skip-browser-tests.
@pytest.fixture(scope="session")
def browser(request):
    if request.config.getoption("--skip-browser-tests"):
        pytest.skip("--skip-browser-tests given")
    try:
        from playwright import sync_api
    except ImportError:
        pytest.fail(f"Playwright is not installed: {BROWSER_SETUP}", pytrace=False)
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except sync_api.Error as error:
            pytest.fail(f"Playwright's Chromium is not installed ({error}): {BROWSER_SETUP}", pytrace=False)
        yield launched
        launched.close()


@pytest.fixture
def page(browser):
    """A fresh page; `page.errors` collects any uncaught page errors."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    # Only the test server is reachable: a sanitizer regression must not
    # make the browser fetch a real site (the tests watch requests instead).
    context.route(lambda url: not url.startswith("http://127.0.0.1"), lambda route: route.abort())
    new_page = context.new_page()
    errors = []
    new_page.on("pageerror", lambda error: errors.append(str(error)))
    new_page.errors = errors
    yield new_page
    context.close()
