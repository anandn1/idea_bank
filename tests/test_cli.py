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


def test_show_includes_linked_goals_current_and_completed(run_cli):
    idea = parse(run_cli("ship the migration", "--json"))
    current = parse(
        run_cli(
            "goal",
            "add",
            "draft it",
            "--idea",
            str(idea["id"]),
            "--date",
            "2026-09-01",
            "--json",
        )
    )
    done = parse(
        run_cli(
            "goal",
            "add",
            "outline it",
            "--idea",
            str(idea["id"]),
            "--date",
            "2026-08-01",
            "--json",
        )
    )
    run_cli("goal", "done", str(done["id"]), "--date", "2026-08-01", "--json")

    shown = parse(run_cli("show", str(idea["id"]), "--json"))

    goals_by_id = {g["id"]: g for g in shown["goals"]}
    assert goals_by_id[current["id"]]["completed"] is False
    assert goals_by_id[done["id"]]["completed"] is True


def test_show_no_linked_goals_is_empty_list(run_cli):
    idea = parse(run_cli("standalone idea", "--json"))
    shown = parse(run_cli("show", str(idea["id"]), "--json"))
    assert shown["goals"] == []


def test_show_lists_a_goal_linked_to_this_idea_among_several(run_cli):
    idea_a = parse(run_cli("idea A", "--json"))
    idea_b = parse(run_cli("idea B", "--json"))
    goal = parse(
        run_cli(
            "goal",
            "add",
            "shared goal",
            "--idea",
            str(idea_a["id"]),
            "--idea",
            str(idea_b["id"]),
            "--json",
        )
    )

    shown_a = parse(run_cli("show", str(idea_a["id"]), "--json"))
    shown_b = parse(run_cli("show", str(idea_b["id"]), "--json"))

    assert [g["id"] for g in shown_a["goals"]] == [goal["id"]]
    assert [g["id"] for g in shown_b["goals"]] == [goal["id"]]
    assert sorted(shown_a["goals"][0]["idea_ids"]) == sorted(
        [idea_a["id"], idea_b["id"]]
    )


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


def test_edit_sets_notes(run_cli):
    created = parse(run_cli("x", "--json"))
    idea = parse(
        run_cli("edit", str(created["id"]), "--notes", "waiting on legal", "--json")
    )
    assert idea["notes"] == "waiting on legal"


def test_edit_unset_notes(run_cli):
    created = parse(run_cli("x", "--json"))
    run_cli("edit", str(created["id"]), "--notes", "temp", "--json")
    idea = parse(run_cli("edit", str(created["id"]), "--unset-notes", "--json"))
    assert idea["notes"] is None


def test_edit_notes_and_unset_notes_together_fails(run_cli):
    created = parse(run_cli("x", "--json"))
    result = run_cli(
        "edit", str(created["id"]), "--notes", "a", "--unset-notes", "--json"
    )
    assert result.returncode == 2  # argparse mutually-exclusive-group rejection


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


# ---- frontier status ----


def test_capture_frontier_short_flag(run_cli):
    result = run_cli("-f", "a moonshot", "--json")
    assert parse(result)["status"] == "frontier"


def test_move_to_frontier(run_cli):
    created = parse(run_cli("x", "--json"))
    idea = parse(run_cli("move", str(created["id"]), "-f", "--json"))
    assert idea["status"] == "frontier"


# ---- goal ----
#
# A goal is its own text, optionally linked to an idea, always
# self-reported as done via `goal done`/`goal undo`.


def test_goal_add_one_off(run_cli):
    goal = parse(run_cli("goal", "add", "walk 10000 steps", "--json"))
    assert goal["text"] == "walk 10000 steps"
    assert goal["weekdays"] is None
    assert goal["idea_ids"] == []


def test_goal_add_weekdays_daily(run_cli):
    goal = parse(
        run_cli("goal", "add", "walk 10000 steps", "--weekdays", "daily", "--json")
    )
    assert goal["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert goal["target_date"] is None


def test_goal_add_weekdays_single_day(run_cli):
    goal = parse(run_cli("goal", "add", "gym", "--weekdays", "mon", "--json"))
    assert goal["weekdays"] == [0]


def test_goal_add_weekdays_abbreviation_list_sorted_and_deduped(run_cli):
    goal = parse(
        run_cli("goal", "add", "gym", "--weekdays", "fri,mon,wed,mon", "--json")
    )
    assert goal["weekdays"] == [0, 2, 4]


def test_goal_add_weekdays_weekdays_shorthand(run_cli):
    goal = parse(run_cli("goal", "add", "standup", "--weekdays", "weekdays", "--json"))
    assert goal["weekdays"] == [0, 1, 2, 3, 4]


def test_goal_add_weekdays_invalid_value_fails(run_cli):
    result = run_cli("goal", "add", "x", "--weekdays", "bogus", "--json")
    assert result.returncode == 1
    assert "invalid --weekdays" in parse(result)["error"]


def test_goal_add_weekdays_with_date_fails(run_cli):
    result = run_cli(
        "goal", "add", "walk", "--weekdays", "daily", "--date", "2026-09-05", "--json"
    )
    assert result.returncode == 1


def test_goal_add_one_off_arbitrary_future_date(run_cli):
    goal = parse(
        run_cli("goal", "add", "review manuscript", "--date", "2026-12-25", "--json")
    )
    assert goal["target_date"] == "2026-12-25"
    assert goal["weekdays"] is None


def test_goal_add_linked_to_idea(run_cli):
    idea = parse(run_cli("run every day", "--json"))
    goal = parse(
        run_cli("goal", "add", "walk 10000 steps", "--idea", str(idea["id"]), "--json")
    )
    assert goal["idea_ids"] == [idea["id"]]


def test_goal_add_linked_to_several_ideas(run_cli):
    idea_a = parse(run_cli("idea A", "--json"))
    idea_b = parse(run_cli("idea B", "--json"))
    goal = parse(
        run_cli(
            "goal",
            "add",
            "shared goal",
            "--idea",
            str(idea_a["id"]),
            "--idea",
            str(idea_b["id"]),
            "--json",
        )
    )
    assert sorted(goal["idea_ids"]) == sorted([idea_a["id"], idea_b["id"]])


def test_goal_add_linked_to_missing_idea_among_several_fails(run_cli):
    idea = parse(run_cli("real idea", "--json"))
    result = run_cli(
        "goal", "add", "x", "--idea", str(idea["id"]), "--idea", "9999", "--json"
    )
    assert result.returncode == 1


def test_goal_add_missing_idea_fails(run_cli):
    result = run_cli("goal", "add", "x", "--idea", "9999", "--json")
    assert result.returncode == 1


def test_goal_add_empty_text_fails(run_cli):
    result = run_cli("goal", "add", "   ", "--json")
    assert result.returncode == 1


def test_goal_list_empty(run_cli):
    result = run_cli("goal", "list")
    assert result.returncode == 0
    assert "no goals due" in result.stdout


def test_goal_list_shows_completion(run_cli):
    parse(run_cli("goal", "add", "x", "--json"))

    before = parse(run_cli("goal", "list", "--json"))
    assert before["goals"][0]["completed_at"] is None

    goal_id = before["goals"][0]["id"]
    run_cli("goal", "done", str(goal_id), "--json")
    after = parse(run_cli("goal", "list", "--json"))
    assert after["goals"][0]["completed_at"] is not None


def test_goal_done_and_undo(run_cli):
    goal = parse(run_cli("goal", "add", "x", "--json"))

    run_cli("goal", "done", str(goal["id"]), "--json")
    assert (
        parse(run_cli("goal", "list", "--json"))["goals"][0]["completed_at"] is not None
    )

    run_cli("goal", "undo", str(goal["id"]), "--json")
    assert parse(run_cli("goal", "list", "--json"))["goals"][0]["completed_at"] is None


def test_goal_done_missing_id_fails(run_cli):
    result = run_cli("goal", "done", "9999", "--json")
    assert result.returncode == 1


def test_goal_done_batch(run_cli):
    ids = [parse(run_cli("goal", "add", t, "--json"))["id"] for t in ("a", "b")]
    result = run_cli("goal", "done", *map(str, ids), "--json")
    assert result.returncode == 0
    goals = parse(run_cli("goal", "list", "--json"))["goals"]
    assert all(g["completed_at"] for g in goals)


def test_goal_stop_recurring_removes_it_from_todays_list(run_cli):
    goal = parse(run_cli("goal", "add", "walk", "--weekdays", "daily", "--json"))
    result = run_cli("goal", "stop", str(goal["id"]), "--json")
    assert result.returncode == 0
    assert parse(run_cli("goal", "list", "--json"))["goals"] == []


def test_goal_list_weekday_tag_formatting(run_cli):
    from datetime import date, timedelta

    run_cli("goal", "add", "gym", "--weekdays", "mon,wed,fri", "--json")
    # find the next Mon/Wed/Fri on or after today, so the goal is actually
    # due on the date we ask about regardless of which day the suite runs
    due_date = date.today()
    while due_date.weekday() not in (0, 2, 4):
        due_date += timedelta(days=1)

    result = run_cli("goal", "list", "--date", due_date.isoformat())
    assert result.returncode == 0
    assert "Mon/Wed/Fri" in result.stdout


def test_goal_stop_one_off_fails(run_cli):
    goal = parse(run_cli("goal", "add", "x", "--json"))
    result = run_cli("goal", "stop", str(goal["id"]), "--json")
    assert result.returncode == 1


def test_goal_remove(run_cli):
    goal = parse(run_cli("goal", "add", "x", "--json"))
    result = run_cli("goal", "remove", str(goal["id"]), "--json")
    assert result.returncode == 0
    assert parse(run_cli("goal", "list", "--json"))["goals"] == []


def test_goal_remove_missing_fails(run_cli):
    result = run_cli("goal", "remove", "9999", "--json")
    assert result.returncode == 1


def test_goal_link_sets_idea_id(run_cli):
    goal = parse(run_cli("goal", "add", "walk 10000 steps", "--json"))  # no idea yet
    idea = parse(run_cli("run every day", "--json"))
    result = run_cli("goal", "link", str(goal["id"]), str(idea["id"]), "--json")
    assert result.returncode == 0
    assert parse(result)["idea_ids"] == [idea["id"]]


def test_goal_link_adds_a_second_link_without_removing_the_first(run_cli):
    idea_a = parse(run_cli("idea A", "--json"))
    idea_b = parse(run_cli("idea B", "--json"))
    goal = parse(run_cli("goal", "add", "x", "--idea", str(idea_a["id"]), "--json"))
    result = run_cli("goal", "link", str(goal["id"]), str(idea_b["id"]), "--json")
    assert result.returncode == 0
    assert sorted(parse(result)["idea_ids"]) == sorted([idea_a["id"], idea_b["id"]])


def test_goal_link_missing_goal_fails(run_cli):
    idea = parse(run_cli("x", "--json"))
    result = run_cli("goal", "link", "9999", str(idea["id"]), "--json")
    assert result.returncode == 1


def test_goal_link_missing_idea_fails(run_cli):
    goal = parse(run_cli("goal", "add", "x", "--json"))
    result = run_cli("goal", "link", str(goal["id"]), "9999", "--json")
    assert result.returncode == 1


def test_goal_unlink_removes_just_that_idea(run_cli):
    idea = parse(run_cli("run every day", "--json"))
    goal = parse(
        run_cli("goal", "add", "walk 10000 steps", "--idea", str(idea["id"]), "--json")
    )
    result = run_cli("goal", "unlink", str(goal["id"]), str(idea["id"]), "--json")
    assert result.returncode == 0
    assert parse(result)["idea_ids"] == []


def test_goal_unlink_leaves_other_links_alone(run_cli):
    idea_a = parse(run_cli("idea A", "--json"))
    idea_b = parse(run_cli("idea B", "--json"))
    goal = parse(
        run_cli(
            "goal",
            "add",
            "x",
            "--idea",
            str(idea_a["id"]),
            "--idea",
            str(idea_b["id"]),
            "--json",
        )
    )
    result = run_cli("goal", "unlink", str(goal["id"]), str(idea_a["id"]), "--json")
    assert result.returncode == 0
    assert parse(result)["idea_ids"] == [idea_b["id"]]


def test_goal_unlink_missing_goal_fails(run_cli):
    idea = parse(run_cli("x", "--json"))
    result = run_cli("goal", "unlink", "9999", str(idea["id"]), "--json")
    assert result.returncode == 1


def test_goal_streak_json_shape(run_cli):
    result = run_cli("goal", "streak", "--json")
    assert result.returncode == 0
    streak = parse(result)
    assert set(streak) >= {
        "streak",
        "longest",
        "today_complete",
        "today_done",
        "today_total",
        "xp",
    }


def test_goal_streak_advances_after_completion(run_cli):
    goal = parse(run_cli("goal", "add", "x", "--json"))
    run_cli("goal", "done", str(goal["id"]), "--json")

    streak = parse(run_cli("goal", "streak", "--json"))
    assert streak["today_complete"] is True
    assert streak["streak"] == 1
    assert streak["xp"] == 1


def test_goal_no_subcommand_fails(run_cli):
    result = run_cli("goal", "--json")
    assert result.returncode == 1


def test_goal_history_empty(run_cli):
    result = run_cli("goal", "history", "--json")
    assert result.returncode == 0
    assert parse(result) == []


def test_goal_history_includes_completed_one_off(run_cli):
    goal = parse(
        run_cli("goal", "add", "draft the proposal", "--date", "2026-08-01", "--json")
    )
    run_cli("goal", "done", str(goal["id"]), "--date", "2026-08-01", "--json")

    history = parse(run_cli("goal", "history", "--json"))
    assert [g["id"] for g in history] == [goal["id"]]
    assert history[0]["times_completed"] == 1


def test_goal_history_excludes_active_recurring_goal(run_cli):
    goal = parse(run_cli("goal", "add", "walk", "--weekdays", "daily", "--json"))
    run_cli(
        "goal", "done", str(goal["id"]), "--json"
    )  # completing today isn't stopping it

    assert parse(run_cli("goal", "history", "--json")) == []


def test_goal_history_includes_stopped_recurring_goal(run_cli):
    goal = parse(run_cli("goal", "add", "walk", "--weekdays", "daily", "--json"))
    run_cli("goal", "stop", str(goal["id"]), "--json")

    history = parse(run_cli("goal", "history", "--json"))
    assert [g["id"] for g in history] == [goal["id"]]


def test_goal_history_shows_linked_idea_text(run_cli):
    idea = parse(run_cli("ship the migration", "--json"))
    goal = parse(
        run_cli(
            "goal",
            "add",
            "draft it",
            "--idea",
            str(idea["id"]),
            "--date",
            "2026-08-01",
            "--json",
        )
    )
    run_cli("goal", "done", str(goal["id"]), "--date", "2026-08-01", "--json")

    result = run_cli("goal", "history")
    assert result.returncode == 0
    assert "ship the migration" in result.stdout


def test_delete_idea_unlinks_its_goal_but_keeps_it(run_cli):
    idea = parse(run_cli("run every day", "--json"))
    goal = parse(
        run_cli("goal", "add", "walk 10000 steps", "--idea", str(idea["id"]), "--json")
    )
    run_cli("delete", str(idea["id"]), "--json")

    goals = parse(run_cli("goal", "list", "--json"))["goals"]
    assert len(goals) == 1
    assert goals[0]["id"] == goal["id"]
    assert goals[0]["idea_ids"] == []


def test_delete_idea_only_removes_that_ones_link(run_cli):
    idea_a = parse(run_cli("idea A", "--json"))
    idea_b = parse(run_cli("idea B", "--json"))
    goal = parse(
        run_cli(
            "goal",
            "add",
            "x",
            "--idea",
            str(idea_a["id"]),
            "--idea",
            str(idea_b["id"]),
            "--json",
        )
    )
    run_cli("delete", str(idea_a["id"]), "--json")

    goals = parse(run_cli("goal", "list", "--json"))["goals"]
    assert goals[0]["idea_ids"] == [idea_b["id"]]


# ---- help / misc ----


def test_help_exits_zero(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0
    assert "capture" in result.stdout


def test_subcommand_help_exits_zero(run_cli):
    result = run_cli("move", "--help")
    assert result.returncode == 0
