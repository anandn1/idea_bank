"""End-to-end tests for the `idea` CLI, invoked exactly as a user or agent
would: as a subprocess, asserting on stdout, exit codes, and JSON shape.
Each test gets its own isolated DB via the run_cli fixture.
"""

import json


def parse(result):
    return json.loads(result.stdout)


# ---- capture ----


def test_capture_default_status_is_inbox(run_cli):
    result = run_cli("capture", "hello world", "--json")
    idea = parse(result)

    assert result.returncode == 0
    assert idea["text"] == "hello world"
    assert idea["status"] == "inbox"
    assert idea["fields"] == {}


def test_bare_capture_shorthand(run_cli):
    result = run_cli("just some text", "--json")
    assert parse(result)["text"] == "just some text"


def test_capture_status_short_flag(run_cli):
    result = run_cli("-q", "queued idea", "--json")
    assert parse(result)["status"] == "queued"


def test_capture_status_long_flag(run_cli):
    result = run_cli("--status", "horizon", "someday idea", "--json")
    assert parse(result)["status"] == "horizon"


def test_capture_with_fields(run_cli):
    result = run_cli(
        "with fields", "--field", "priority=high", "--field", "due=2026-10-01", "--json"
    )
    assert parse(result)["fields"] == {"priority": "high", "due": "2026-10-01"}


def test_capture_malformed_field_fails(run_cli):
    result = run_cli("bad", "--field", "noequals", "--json")
    assert result.returncode == 1
    assert "error" in parse(result)


def test_capture_empty_text_fails(run_cli):
    result = run_cli("capture", "   ", "--json")
    assert result.returncode == 1


def test_capture_stdin_bulk(run_cli):
    result = run_cli("capture", "--stdin", "-q", "--json", input="one\ntwo\nthree\n")
    ideas = parse(result)

    assert result.returncode == 0
    assert [i["text"] for i in ideas] == ["one", "two", "three"]
    assert all(i["status"] == "queued" for i in ideas)


def test_capture_stdin_skips_blank_lines(run_cli):
    result = run_cli("capture", "--stdin", "--json", input="one\n\n\ntwo\n")
    assert len(parse(result)) == 2


def test_capture_stdin_with_text_args_fails(run_cli):
    result = run_cli("capture", "--stdin", "also text", "--json", input="one\n")
    assert result.returncode == 1


def test_capture_stdin_all_blank_fails(run_cli):
    result = run_cli("capture", "--stdin", "--json", input="\n\n")
    assert result.returncode == 1


# ---- list ----


def test_list_empty(run_cli):
    result = run_cli("list")
    assert result.returncode == 0
    assert "no ideas found" in result.stdout


def test_list_json_shape(run_cli):
    run_cli("first", "--json")
    run_cli("-q", "second", "--json")

    ideas = parse(run_cli("list", "--json"))
    assert len(ideas) == 2


def test_list_filtered_by_status(run_cli):
    run_cli("inbox one", "--json")
    run_cli("-q", "queued one", "--json")

    ideas = parse(run_cli("list", "-q", "--json"))
    assert [i["text"] for i in ideas] == ["queued one"]


# ---- show ----


def test_show_single(run_cli):
    created = parse(run_cli("show me", "--json"))
    idea = parse(run_cli("show", str(created["id"]), "--json"))
    assert idea["text"] == "show me"


def test_show_batch_returns_array(run_cli):
    a = parse(run_cli("a", "--json"))
    b = parse(run_cli("b", "--json"))

    ideas = parse(run_cli("show", str(a["id"]), str(b["id"]), "--json"))
    assert len(ideas) == 2


def test_show_missing_id_fails(run_cli):
    result = run_cli("show", "9999", "--json")
    assert result.returncode == 1
    assert "error" in parse(result)


# ---- move ----


def test_move_trailing_word(run_cli):
    created = parse(run_cli("move me", "--json"))
    idea = parse(run_cli("move", str(created["id"]), "active", "--json"))
    assert idea["status"] == "active"


def test_move_flag_form(run_cli):
    created = parse(run_cli("move me too", "--json"))
    idea = parse(run_cli("move", str(created["id"]), "-x", "--json"))
    assert idea["status"] == "archive"


def test_move_batch(run_cli):
    ids = [parse(run_cli(t, "--json"))["id"] for t in ("a", "b", "c")]
    ideas = parse(run_cli("move", *map(str, ids), "-x", "--json"))
    assert len(ideas) == 3
    assert all(i["status"] == "archive" for i in ideas)


def test_move_both_trailing_and_flag_fails(run_cli):
    created = parse(run_cli("x", "--json"))
    result = run_cli("move", str(created["id"]), "active", "-x", "--json")
    assert result.returncode == 1


def test_move_neither_trailing_nor_flag_fails(run_cli):
    created = parse(run_cli("x", "--json"))
    result = run_cli("move", str(created["id"]), "--json")
    assert result.returncode == 1


def test_move_missing_id_is_atomic(run_cli):
    a = parse(run_cli("a", "--json"))
    result = run_cli("move", str(a["id"]), "9999", "active", "--json")
    assert result.returncode == 1

    # a must be untouched -- a batch with one bad id changes nothing
    check = parse(run_cli("show", str(a["id"]), "--json"))
    assert check["status"] == "inbox"


def test_move_invalid_status_word_fails_with_clear_message(run_cli):
    created = parse(run_cli("x", "--json"))
    result = run_cli("move", str(created["id"]), "not_a_status", "--json")
    assert result.returncode == 1
    assert "invalid status" in parse(result)["error"]


def test_move_unknown_flag_exits_2(run_cli):
    # argparse itself still rejects a genuinely unknown option
    created = parse(run_cli("x", "--json"))
    result = run_cli("move", str(created["id"]), "active", "--nonsense-flag")
    assert result.returncode == 2


# ---- edit ----


def test_edit_text(run_cli):
    created = parse(run_cli("original", "--json"))
    idea = parse(run_cli("edit", str(created["id"]), "new text", "--json"))
    assert idea["text"] == "new text"


def test_edit_field_only_no_text_required(run_cli):
    created = parse(run_cli("keep me", "--json"))
    idea = parse(run_cli("edit", str(created["id"]), "--field", "owner=me", "--json"))
    assert idea["text"] == "keep me"
    assert idea["fields"] == {"owner": "me"}


def test_edit_field_merges_not_replaces(run_cli):
    created = parse(run_cli("x", "--field", "a=1", "--json"))
    idea = parse(run_cli("edit", str(created["id"]), "--field", "b=2", "--json"))
    assert idea["fields"] == {"a": "1", "b": "2"}


def test_edit_unset_field(run_cli):
    created = parse(run_cli("x", "--field", "a=1", "--field", "b=2", "--json"))
    idea = parse(run_cli("edit", str(created["id"]), "--unset-field", "a", "--json"))
    assert idea["fields"] == {"b": "2"}


def test_edit_nothing_to_change_fails(run_cli):
    created = parse(run_cli("x", "--json"))
    result = run_cli("edit", str(created["id"]), "--json")
    assert result.returncode == 1


def test_edit_empty_text_fails(run_cli):
    created = parse(run_cli("x", "--json"))
    result = run_cli("edit", str(created["id"]), "   ", "--json")
    assert result.returncode == 1


def test_edit_missing_id_fails(run_cli):
    result = run_cli("edit", "9999", "text", "--json")
    assert result.returncode == 1


# ---- delete ----


def test_delete_single(run_cli):
    created = parse(run_cli("delete me", "--json"))
    result = run_cli("delete", str(created["id"]), "--json")
    assert result.returncode == 0
    assert parse(result) == {"deleted": True, "id": created["id"]}
    assert run_cli("show", str(created["id"]), "--json").returncode == 1


def test_delete_batch(run_cli):
    ids = [parse(run_cli(t, "--json"))["id"] for t in ("a", "b")]
    result = parse(run_cli("delete", *map(str, ids), "--json"))
    assert len(result) == 2


def test_delete_missing_id_is_atomic(run_cli):
    a = parse(run_cli("a", "--json"))
    result = run_cli("delete", str(a["id"]), "9999", "--json")
    assert result.returncode == 1

    # a must NOT have been deleted
    assert run_cli("show", str(a["id"]), "--json").returncode == 0


# ---- help / misc ----


def test_help_exits_zero(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0
    assert "capture" in result.stdout


def test_subcommand_help_exits_zero(run_cli):
    result = run_cli("move", "--help")
    assert result.returncode == 0
