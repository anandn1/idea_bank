"""Runs the JavaScript tests in tests/js/ (Node's built-in test runner, no
npm packages) so `pytest` stays the single command for the whole suite.
Skipped when node isn't installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TEST_DIR = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_suite_passes():
    test_files = sorted(str(path) for path in JS_TEST_DIR.glob("*.test.js"))
    assert test_files, f"no *.test.js files found in {JS_TEST_DIR}"

    result = subprocess.run(
        ["node", "--test", *test_files], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stdout + result.stderr
