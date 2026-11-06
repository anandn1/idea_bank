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


# ---- goal stats rendering ----


def _rate(done, due):
    return {"done": done, "due": due, "rate": round(done / due, 4) if due else None}


def _heatmap_days(start, count, done=1, due=1):
    first = dbutil.date_cls.fromisoformat(start)
    return [
        {"date": (first + dbutil.timedelta(days=n)).isoformat(), "done": done, "due": due}
        for n in range(count)
    ]


@pytest.mark.parametrize(
    "day, expected",
    [
        ({"done": 0, "due": 0}, "·"),
        ({"done": 0, "due": 2}, "-"),
        ({"done": 1, "due": 6}, "░"),
        ({"done": 1, "due": 3}, "░"),
        ({"done": 1, "due": 2}, "▒"),
        ({"done": 2, "due": 3}, "▒"),
        ({"done": 5, "due": 6}, "▓"),
        ({"done": 1, "due": 1}, "█"),
    ],
)
def test_heatmap_cell(cli, day, expected):
    assert cli.heatmap_cell(day) == expected


def test_format_rate_nothing_due(cli):
    assert cli.format_rate(_rate(0, 0)) == "  --  (nothing due)"


def test_format_rate_shows_percent_then_done_over_due(cli):
    assert cli.format_rate(_rate(1, 2)) == " 50%  (1/2)"


def test_rate_bar_fill_and_width(cli):
    bar = cli.rate_bar(_rate(1, 4))
    assert bar == "█" * 5 + "·" * 15


def test_rate_bar_rounds_to_nearest_cell(cli):
    assert cli.rate_bar(_rate(1, 3)).count("█") == 7  # 6.67 cells


def test_rate_bar_nothing_due_is_empty(cli):
    assert cli.rate_bar(_rate(0, 0)) == "·" * cli.RATE_BAR_WIDTH


def test_heatmap_lines_empty(cli):
    assert cli.heatmap_lines([]) == []


def test_heatmap_lines_pads_first_week_back_to_monday(cli):
    # 2026-09-10 is a Thursday: Mon-Wed of the first column are blank
    lines = cli.heatmap_lines(_heatmap_days("2026-09-10", 4))
    assert lines == [
        "  Mon   ",
        "  Tue   ",
        "  Wed   ",
        "  Thu  █",
        "  Fri  █",
        "  Sat  █",
        "  Sun  █",
    ]


def test_heatmap_lines_shows_exactly_the_last_12_weeks(cli):
    # 200 days ending on a Thursday: still exactly 12 columns
    lines = cli.heatmap_lines(_heatmap_days("2026-02-23", 200))
    assert len(lines) == 7
    assert all(len(line.split()) - 1 == cli.CLI_HEATMAP_WEEKS for line in lines[:4])
    assert len(lines[4].split()) - 1 == cli.CLI_HEATMAP_WEEKS - 1  # Fri not reached yet


def test_heatmap_lines_newest_week_on_the_right(cli):
    heatmap = [{"date": "2026-09-07", "done": 0, "due": 1}] + _heatmap_days("2026-09-08", 7)
    assert cli.heatmap_lines(heatmap)[0] == "  Mon  - █"


def _stats(recurring=(), one_offs=None, heatmap=()):
    return {
        "today": "2026-09-10",
        "totals": {"checkoffs": 3, "tracked_days": 4, "perfect_days": 2},
        "rates": [
            {"window": "7d", **_rate(1, 2)},
            {"window": "30d", **_rate(1, 4)},
            {"window": "90d", **_rate(3, 4)},
            {"window": "all", **_rate(0, 0)},
        ],
        "weekdays": [{"weekday": 0, **_rate(1, 2)}]
        + [{"weekday": d, **_rate(0, 0)} for d in range(1, 7)],
        "heatmap": list(heatmap),
        "recurring": list(recurring),
        "one_offs": one_offs or {"done": 1, "missed": 1, "pending": 2},
    }


def test_print_goal_stats_totals_rates_and_one_offs(cli, capsys):
    cli.print_goal_stats(_stats())
    out = capsys.readouterr().out
    assert "check-offs 3   perfect days 2/4" in out
    assert "last 7d    50%  (1/2)" in out
    assert "last 30d   25%  (1/4)" in out
    assert "last 90d   75%  (3/4)" in out
    assert "all time    --  (nothing due)" in out
    assert "one-off goals\n  1 done, 1 missed, 2 pending" in out


def test_print_goal_stats_weekday_section(cli, capsys):
    cli.print_goal_stats(_stats())
    out = capsys.readouterr().out
    assert "by weekday\n  Mon  " + "█" * 10 + "·" * 10 + "   50%  (1/2)\n" in out
    assert "  Tue  " + "·" * 20 + "    --  (nothing due)" in out


def test_print_goal_stats_active_goal_never_done(cli, capsys):
    goal = {
        "id": 3, "text": "gym", "weekdays": [0, 2], "archived_at": None,
        "streak": 0, "best_streak": 0, "last_done": None, **_rate(0, 2),
    }
    cli.print_goal_stats(_stats(recurring=[goal]))
    out = capsys.readouterr().out
    assert "  #3 (Mon/Wed) gym\n" in out
    assert "0%  (0/2), streak 0, best 0, last done never" in out
    assert "[stopped" not in out


def test_print_goal_stats_prints_heatmap_rows(cli, capsys):
    heatmap = [{"date": "2026-09-07", "done": 0, "due": 1}] + _heatmap_days("2026-09-08", 3)
    cli.print_goal_stats(_stats(heatmap=heatmap))
    out = capsys.readouterr().out
    assert "last 12 weeks" in out
    assert "\n  Mon  -\n  Tue  █\n" in out


def test_print_goal_stats_recurring_goal_with_stopped_label(cli, capsys):
    goal = {
        "id": 7, "text": "walk", "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "archived_at": "2026-09-04 09:00:00", "streak": 0, "best_streak": 3,
        "last_done": "2026-09-03", **_rate(3, 3),
    }
    cli.print_goal_stats(_stats(recurring=[goal]))
    out = capsys.readouterr().out
    assert "#7 (daily) walk [stopped 2026-09-04]" in out
    assert "100%  (3/3), streak 0, best 3, last done 2026-09-03" in out
