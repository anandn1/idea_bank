"""Unit tests for the pure helper functions in cli/idea.

cli/idea has no .py extension (it's a #!/usr/bin/env python3 script meant
to be run directly or symlinked onto PATH), so it's loaded here via
importlib rather than a normal import. Its own `import dbutil` still
resolves to the same cached dbutil module as everywhere else in the
suite, so the db_path/conn fixtures apply to it too.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

import dbutil

CLI_PATH = Path(__file__).resolve().parent.parent / "cli" / "idea"


def load_cli_module():
    # spec_from_file_location can't infer a loader for an extension-less
    # file on its own, so hand it one explicitly.
    loader = importlib.machinery.SourceFileLoader("idea_cli_under_test", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return load_cli_module()


# ---- parse_ids_and_status ----


def test_parse_ids_and_status_trailing_word(cli):
    ids, status = cli.parse_ids_and_status(["12", "13", "active"], None)
    assert ids == [12, 13]
    assert status == "active"


def test_parse_ids_and_status_flag_form(cli):
    ids, status = cli.parse_ids_and_status(["12", "13"], "archive")
    assert ids == [12, 13]
    assert status == "archive"


def test_parse_ids_and_status_single_id(cli):
    ids, status = cli.parse_ids_and_status(["12", "active"], None)
    assert ids == [12]
    assert status == "active"


def test_parse_ids_and_status_both_given_is_error(cli):
    ids, err = cli.parse_ids_and_status(["12", "active"], "archive")
    assert ids is None
    assert "only once" in err


def test_parse_ids_and_status_neither_given_is_error(cli):
    ids, err = cli.parse_ids_and_status(["12"], None)
    assert ids is None
    assert "missing target status" in err


def test_parse_ids_and_status_invalid_id_is_error(cli):
    ids, err = cli.parse_ids_and_status(["12", "abc", "active"], None)
    assert ids is None
    assert "invalid idea id" in err


def test_parse_ids_and_status_empty_tokens_is_error(cli):
    ids, err = cli.parse_ids_and_status([], None)
    assert ids is None
    assert "no idea id" in err


# ---- parse_field_args ----


def test_parse_field_args_basic(cli):
    fields, err = cli.parse_field_args(["a=1", "b=2"])
    assert err is None
    assert fields == {"a": "1", "b": "2"}


def test_parse_field_args_none_returns_empty_dict(cli):
    fields, err = cli.parse_field_args(None)
    assert err is None
    assert fields == {}


def test_parse_field_args_missing_equals_is_error(cli):
    fields, err = cli.parse_field_args(["noequals"])
    assert fields is None
    assert "expected key=value" in err


def test_parse_field_args_empty_key_is_error(cli):
    fields, err = cli.parse_field_args(["=value"])
    assert fields is None
    assert "empty key" in err


def test_parse_field_args_value_can_contain_equals(cli):
    fields, err = cli.parse_field_args(["url=https://example.com?a=b"])
    assert err is None
    assert fields == {"url": "https://example.com?a=b"}


def test_parse_field_args_later_duplicate_key_wins(cli):
    fields, err = cli.parse_field_args(["a=1", "a=2"])
    assert err is None
    assert fields == {"a": "2"}


# ---- missing_ids ----


def test_missing_ids(cli, conn):
    id1 = dbutil.add_idea("one")
    id2 = dbutil.add_idea("two")

    assert cli.missing_ids(conn, [id1, id2, 9999]) == [9999]


def test_missing_ids_none_missing(cli, conn):
    id1 = dbutil.add_idea("one")

    assert cli.missing_ids(conn, [id1]) == []
