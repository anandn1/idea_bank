"""Browser tests for the full idea view (static/idea.html?id=N): what it
shows from /api/ideas/<id>/overview and that each edit on it saves.
Fixtures (base_url, gui_db_path, page) are in conftest.py; notes rendering
and the notes read/edit toggle are covered in test_gui_notes.py."""

import time
from datetime import date, datetime, timedelta

from conftest import FIXED_TODAY
from gui_support import api, get_idea, get_overview, make_goal, make_idea, run_sql

DAILY = [0, 1, 2, 3, 4, 5, 6]
NOTES_SAVE_WAIT_MS = 5000  # the view debounces notes saves by ~1.2s
PAGEHIDE_SAVE_TIMEOUT_S = 3


def open_view(page, base_url, idea_id):
    page.goto(f"{base_url}/idea.html?id={idea_id}")
    page.wait_for_selector("#idea-view:not([hidden])")


def idea_save(page, timeout=None):
    """Wait for the view's next PATCH of the idea to come back."""
    return page.expect_response(
        lambda r: r.request.method == "PATCH" and "/api/ideas/" in r.url,
        **({"timeout": timeout} if timeout else {}),
    )


def days_ago(n):
    return (date.fromisoformat(FIXED_TODAY) - timedelta(days=n)).isoformat()


def backdate_goal(db_path, goal_id, days):
    run_sql(
        db_path,
        "UPDATE goals SET created_at = ? WHERE id = ?",
        (f"{days_ago(days)} 08:00:00", goal_id),
    )


def check_off(base_url, goal_id, on_date=None):
    body = {"completed": True, **({"date": on_date} if on_date else {})}
    api(base_url, "PATCH", f"/api/goals/{goal_id}", body)


def make_goal_with_history(base_url, gui_db_path, idea_id):
    """A daily goal created 3 days ago: done 3 and 2 days ago, missed
    yesterday, done today -- 3 of 4 days, current streak 1, best 2."""
    goal = make_goal(base_url, "walk", idea_id, weekdays=DAILY)
    backdate_goal(gui_db_path, goal["id"], 3)
    for day in (days_ago(3), days_ago(2), None):
        check_off(base_url, goal["id"], day)
    return goal


# ---- what it shows ----


def test_hero_shows_title_status_and_meta(page, base_url):
    idea = make_idea(base_url, "couch to 10k", status="active")

    open_view(page, base_url, idea["id"])

    assert page.input_value("#view-title") == "couch to 10k"
    assert page.evaluate("document.getElementById('view-title').offsetHeight") > 20
    assert page.locator("#view-status-pills .selected").inner_text() == "active"
    assert page.inner_text("#view-eyebrow") == f"IDEA #{idea['id']} · DAY 1"
    assert page.inner_text("#view-meta").startswith(
        f"created {idea['created_at'][:16]}"
    )
    assert page.inner_text("#view-cmd") == f"idea show {idea['id']} --full"
    assert page.title() == "couch to 10k"
    assert page.errors == []


def test_meta_shows_relative_time_since_the_idea_was_updated(
    page, base_url, gui_db_path
):
    """relativeTime() runs on the browser's own (real) clock, unlike
    created_at/updated_at themselves, which come from the pinned
    IDEA_BANK_TODAY -- so this sets updated_at straight off the real wall
    clock (like a real user's edit would), not days_ago()/FIXED_TODAY."""
    idea = make_idea(base_url, "steady habit")
    two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    run_sql(
        gui_db_path,
        "UPDATE ideas SET updated_at = ? WHERE id = ?",
        (two_hours_ago, idea["id"]),
    )

    open_view(page, base_url, idea["id"])

    assert page.inner_text("#view-meta").endswith("updated 2h ago")


def test_goal_tag_shows_the_schedule_in_words(page, base_url):
    idea = make_idea(base_url, "scheduled")
    make_goal(base_url, "gym", idea["id"], weekdays=[0, 2, 4])

    open_view(page, base_url, idea["id"])

    assert page.locator(".goal-tag").first.inner_text() == "Mon/Wed/Fri"


def test_progress_bar_shows_share_of_goal_days_done(page, base_url, gui_db_path):
    idea = make_idea(base_url, "with history")
    make_goal_with_history(base_url, gui_db_path, idea["id"])

    open_view(page, base_url, idea["id"])

    assert page.locator(".xp-seg.on").count() == 18  # 75% of 24
    assert (
        page.inner_text("#view-xp-label")
        == "75% of goal-days done · 3/4 · 3 check-offs"
    )


def test_tiles_show_today_streaks_goals_and_check_offs(page, base_url, gui_db_path):
    idea = make_idea(base_url, "tiles")
    make_goal_with_history(base_url, gui_db_path, idea["id"])

    open_view(page, base_url, idea["id"])

    assert page.locator(".view-tile").all_inner_texts() == [
        "1/1\ndue today",
        "1d\ntop streak",
        "2d\nbest streak",
        "1\ngoal linked",
        "3\ncheck-offs",
    ]


def test_no_goals_shows_empty_progress_and_objectives_hint(page, base_url):
    idea = make_idea(base_url, "lonely")

    open_view(page, base_url, idea["id"])

    assert page.locator(".xp-seg.on").count() == 0
    assert "no goal history yet" in page.inner_text("#view-xp-label")
    assert "no goals linked yet" in page.inner_text("#objectives")


def test_objectives_split_current_and_finished(page, base_url):
    idea = make_idea(base_url, "objectives")
    make_goal(base_url, "daily walk", idea["id"], weekdays=DAILY)
    done = make_goal(base_url, "book physio", idea["id"], target_date="2020-01-01")
    check_off(base_url, done["id"], "2020-01-01")
    make_goal(base_url, "parkrun", idea["id"], target_date="2099-01-01")

    open_view(page, base_url, idea["id"])

    objectives = page.locator(".objective")
    assert page.locator(".objective-text").all_inner_texts() == [
        "daily walk",
        "parkrun",
        "book physio",
    ]
    assert page.locator(".objective-group-label").inner_text() == "FINISHED"
    assert objectives.nth(0).locator(".mini-heatmap").count() == 1
    assert "due 2099-01-01" in objectives.nth(1).inner_text()
    assert objectives.nth(1).locator(".goal-check").is_disabled()  # not due today
    assert "done 2020-01-01" in objectives.nth(2).inner_text()
    assert objectives.nth(2).locator(".goal-check").inner_text() == "[x]"
    assert objectives.nth(2).locator(".goal-check").is_disabled()


def test_stopped_recurring_goal_is_finished_and_tagged(page, base_url):
    idea = make_idea(base_url, "stopped habit")
    make_goal(base_url, "active habit", idea["id"], weekdays=DAILY)
    stopped = make_goal(base_url, "old habit", idea["id"], weekdays=DAILY)
    api(base_url, "POST", f"/api/goals/{stopped['id']}/stop")

    open_view(page, base_url, idea["id"])

    finished = page.locator(".objective.finished")
    assert finished.count() == 1
    assert finished.locator(".objective-text").inner_text() == "old habit"
    assert f"stopped {FIXED_TODAY}" in finished.inner_text()


def test_one_off_done_today_can_still_be_undone(page, base_url):
    idea = make_idea(base_url, "today's one-off")
    goal = make_goal(base_url, "call physio", idea["id"])  # one-off, due today
    check_off(base_url, goal["id"])

    open_view(page, base_url, idea["id"])

    check = page.locator(".objective .goal-check")
    assert check.is_enabled()
    assert check.get_attribute("aria-pressed") == "true"
    check.click()
    page.wait_for_function(
        "document.querySelector('.objective .goal-check').textContent === '[ ]'"
    )
    assert get_overview(base_url, idea["id"])["goals"][0]["done_today"] is False


def test_one_off_without_a_target_date_still_renders(page, base_url, gui_db_path):
    idea = make_idea(base_url, "legacy goal")
    goal = make_goal(base_url, "old one-off", idea["id"])
    run_sql(
        gui_db_path, "UPDATE goals SET target_date = NULL WHERE id = ?", (goal["id"],)
    )

    open_view(page, base_url, idea["id"])

    assert page.errors == []
    assert "no date set" in page.locator(".objective").inner_text()


def test_fields_render_as_a_sheet(page, base_url):
    idea = make_idea(base_url, "fielded", fields={"area": "fitness", "budget": "£80"})

    open_view(page, base_url, idea["id"])

    keys = [page.locator(".sheet-key").nth(i).input_value() for i in range(2)]
    values = [page.locator(".sheet-value").nth(i).input_value() for i in range(2)]
    assert keys == ["area", "budget"]
    assert values == ["fitness", "£80"]


def test_chapters_list_notes_headings_and_jump_to_them(page, base_url):
    idea = make_idea(
        base_url, "chaptered", "# Quest\n## Phase 1\ntext\n## Phase 2\n### detail"
    )

    open_view(page, base_url, idea["id"])

    assert page.locator(".chapter").all_inner_texts() == [
        "01\nQuest",
        "02\nPhase 1",
        "03\nPhase 2",
    ]
    assert page.evaluate("[...document.querySelectorAll('.chapter')].map((e) => e.className)") == [
        "chapter top",
        "chapter",
        "chapter",
    ]
    page.locator(".chapter a").nth(2).click()
    assert page.evaluate("location.hash") == "#chapter-3"
    assert page.locator("#chapter-3 .md-h-text").inner_text() == "Phase 2"


def test_raw_html_with_a_heading_class_does_not_break_the_view(page, base_url):
    idea = make_idea(base_url, "fake chapter", '# Real\n\n<div class="md-h md-h2">fake</div>\n\n- [x] task')

    open_view(page, base_url, idea["id"])

    assert page.errors == []
    assert page.locator(".chapter").all_inner_texts() == ["01\nReal", "02\nfake"]


def test_a_heading_quoted_inside_a_callout_is_not_a_chapter(page, base_url):
    idea = make_idea(base_url, "callout heading", "# Top\n\n> [!NOTE]\n> # Inside\n\n## Next")

    open_view(page, base_url, idea["id"])

    assert page.locator(".chapter").all_inner_texts() == ["01\nTop", "02\nNext"]


def test_chapters_follow_the_notes_after_an_edit(page, base_url):
    idea = make_idea(base_url, "rechaptered", "# One")
    open_view(page, base_url, idea["id"])

    page.click("#notes-toggle")
    page.fill("#notes-editor", "# One\n## Two")
    page.click("#notes-toggle")

    assert page.locator(".chapter").all_inner_texts() == ["01\nOne", "02\nTwo"]


def test_chapters_panel_hidden_without_headings(page, base_url):
    idea = make_idea(base_url, "flat notes", "just text")

    open_view(page, base_url, idea["id"])

    assert page.is_hidden("#panel-chapters")


def test_timeline_lists_events_newest_first(page, base_url):
    idea = make_idea(base_url, "timeline", status="active")
    make_goal(base_url, "walk", idea["id"], weekdays=DAILY)

    open_view(page, base_url, idea["id"])

    events = page.locator(".timeline-what").all_inner_texts()
    assert events == ["goal created: walk", "moved inbox → active", "idea created"]


def test_missing_idea_shows_a_notice(page, base_url):
    page.goto(f"{base_url}/idea.html?id=999999")

    page.wait_for_selector("#view-notice:not([hidden])")
    assert "no longer exists" in page.inner_text("#view-notice")
    assert page.is_hidden("#idea-view")


def test_server_error_shows_a_notice(page, base_url):
    idea = make_idea(base_url, "unreachable")
    page.route("**/overview", lambda route: route.fulfill(status=500, body="boom"))

    page.goto(f"{base_url}/idea.html?id={idea['id']}")

    page.wait_for_selector("#view-notice:not([hidden])")
    assert "couldn't load this idea" in page.inner_text("#view-notice")


def test_no_id_in_the_address_shows_a_notice(page, base_url):
    page.goto(f"{base_url}/idea.html")

    page.wait_for_selector("#view-notice:not([hidden])")
    assert "no idea id" in page.inner_text("#view-notice")


# ---- edits save straight away ----


def test_check_off_and_undo_a_goal_for_today(page, base_url):
    idea = make_idea(base_url, "check me")
    make_goal(base_url, "walk", idea["id"], weekdays=DAILY)
    open_view(page, base_url, idea["id"])

    page.locator(".objective .goal-check").click()
    page.wait_for_function(
        "document.querySelector('.objective .goal-check').textContent === '[x]'"
    )
    assert get_overview(base_url, idea["id"])["goals"][0]["done_today"] is True
    assert page.inner_text("#objectives-count") == "1/1 today"

    page.locator(".objective .goal-check").click()
    page.wait_for_function(
        "document.querySelector('.objective .goal-check').textContent === '[ ]'"
    )
    assert get_overview(base_url, idea["id"])["goals"][0]["done_today"] is False


def test_status_change_saves_and_appears_in_timeline(page, base_url):
    idea = make_idea(base_url, "move me")
    open_view(page, base_url, idea["id"])

    with idea_save(page):
        page.click('#view-status-pills button[data-status="horizon"]')
    page.wait_for_function(
        "document.querySelector('.timeline-what').textContent.startsWith('moved')"
    )

    assert get_idea(base_url, idea["id"])["status"] == "horizon"
    assert page.locator("#view-status-pills .selected").inner_text() == "horizon"
    assert page.locator(".timeline-what").first.inner_text() == "moved inbox → horizon"


def test_title_saves_on_enter(page, base_url):
    idea = make_idea(base_url, "old title")
    open_view(page, base_url, idea["id"])

    page.fill("#view-title", "new title")
    with idea_save(page):
        page.keyboard.press("Enter")

    assert get_idea(base_url, idea["id"])["text"] == "new title"


def test_empty_title_is_refused_and_reverted(page, base_url):
    idea = make_idea(base_url, "keep me")
    open_view(page, base_url, idea["id"])

    page.fill("#view-title", "   ")
    page.keyboard.press("Enter")

    assert page.input_value("#view-title") == "keep me"
    assert "can't be empty" in page.inner_text("#view-save-state")
    assert get_idea(base_url, idea["id"])["text"] == "keep me"


def test_escape_discards_a_title_edit_without_saving(page, base_url):
    idea = make_idea(base_url, "unchanged")
    open_view(page, base_url, idea["id"])
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)

    page.fill("#view-title", "typo")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)  # time for a wrongly-fired save to go out

    assert page.input_value("#view-title") == "unchanged"
    assert patches == []


def test_editing_a_field_value_saves(page, base_url):
    idea = make_idea(base_url, "fields", fields={"area": "fitness"})
    open_view(page, base_url, idea["id"])

    page.locator(".sheet-value").fill("running")
    with idea_save(page):
        page.locator(".sheet-value").press("Tab")

    assert get_idea(base_url, idea["id"])["fields"] == {"area": "running"}


def test_adding_a_field_saves_the_key_then_the_value(page, base_url):
    idea = make_idea(base_url, "fields", fields={"area": "fitness"})
    open_view(page, base_url, idea["id"])

    page.click("#field-add")
    page.keyboard.type("shoes")
    with page.expect_response(
        lambda r: r.url.endswith("/overview")
    ):  # the refresh after saving
        with idea_save(page):
            page.keyboard.press("Tab")  # key committed; value still empty
    # the refresh must not have rebuilt the sheet under the focused value input
    assert page.evaluate("document.activeElement.classList.contains('sheet-value')")
    page.keyboard.type("size 9")
    with idea_save(page):
        page.keyboard.press("Tab")

    assert get_idea(base_url, idea["id"])["fields"] == {
        "area": "fitness",
        "shoes": "size 9",
    }


def test_removing_a_field_saves(page, base_url):
    idea = make_idea(base_url, "fields", fields={"area": "fitness", "old": "x"})
    open_view(page, base_url, idea["id"])

    with idea_save(page):
        page.locator('.sheet-remove[aria-label="remove field old"]').click()

    assert get_idea(base_url, idea["id"])["fields"] == {"area": "fitness"}


def test_notes_autosave_after_typing_stops(page, base_url):
    idea = make_idea(base_url, "notes", "# start")
    open_view(page, base_url, idea["id"])

    page.click("#notes-toggle")
    with idea_save(page, timeout=NOTES_SAVE_WAIT_MS):
        page.fill("#notes-editor", "# start\n## added chapter")

    assert get_idea(base_url, idea["id"])["notes"] == "# start\n## added chapter"


def test_clearing_notes_saves_them_as_empty(page, base_url):
    idea = make_idea(base_url, "clear notes", "something")
    open_view(page, base_url, idea["id"])

    page.click("#notes-toggle")
    page.fill("#notes-editor", "")
    with idea_save(page):
        page.locator("#view-title").click()  # blurring the editor saves at once

    assert get_idea(base_url, idea["id"])["notes"] is None


def test_unsaved_notes_are_sent_when_leaving_the_page(page, base_url):
    idea = make_idea(base_url, "leaving", "draft")
    open_view(page, base_url, idea["id"])

    page.click("#notes-toggle")
    page.fill("#notes-editor", "typed just before leaving")
    page.goto(base_url + "/")  # well inside the debounce delay

    deadline = time.monotonic() + PAGEHIDE_SAVE_TIMEOUT_S
    while get_idea(base_url, idea["id"])["notes"] != "typed just before leaving":
        assert time.monotonic() < deadline, "notes weren't saved on leaving the page"
        time.sleep(0.1)


def test_delete_removes_the_idea_and_returns_to_the_board(page, base_url):
    idea = make_idea(base_url, "delete me")
    open_view(page, base_url, idea["id"])

    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#view-delete")
    page.wait_for_url(base_url + "/")

    ids = [i["id"] for i in api(base_url, "GET", "/api/ideas")]
    assert idea["id"] not in ids


def test_delete_from_a_popped_out_window_closes_it(page, base_url):
    idea = make_idea(base_url, "popup delete")
    page.goto(base_url + "/")
    page.keyboard.press("i")
    page.locator(f'.card[data-id="{idea["id"]}"]').click()
    page.keyboard.press("Enter")
    with page.expect_popup() as popup_info:
        page.click("#modal-popout")
    popup = popup_info.value
    popup.wait_for_selector("#idea-view:not([hidden])")

    popup.once("dialog", lambda dialog: dialog.accept())
    with popup.expect_event("close"):
        popup.click("#view-delete")

    ids = [i["id"] for i in api(base_url, "GET", "/api/ideas")]
    assert idea["id"] not in ids


def test_declining_the_delete_prompt_keeps_the_idea(page, base_url):
    idea = make_idea(base_url, "keep after cancel")
    open_view(page, base_url, idea["id"])

    deletes = []
    page.on(
        "request", lambda r: deletes.append(r.url) if r.method == "DELETE" else None
    )
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("#view-delete")
    page.wait_for_timeout(300)  # time for a wrongly-sent DELETE to go out

    assert deletes == []
    assert get_idea(base_url, idea["id"])["text"] == "keep after cancel"


def test_missed_one_off_is_finished_and_says_so(page, base_url):
    idea = make_idea(base_url, "missed")
    make_goal(base_url, "call back", idea["id"], target_date=days_ago(1))

    open_view(page, base_url, idea["id"])

    objective = page.locator(".objective")
    assert "finished" in objective.get_attribute("class")
    assert f"missed · was due {days_ago(1)}" in objective.inner_text()


def test_one_off_due_today_and_not_done_is_current(page, base_url):
    idea = make_idea(base_url, "due today")
    make_goal(base_url, "call today", idea["id"])  # defaults to today

    open_view(page, base_url, idea["id"])

    objective = page.locator(".objective")
    assert "finished" not in objective.get_attribute("class")
    assert "due today" in objective.inner_text()
    assert objective.locator(".goal-check").inner_text() == "[ ]"


def test_mini_heatmap_marks_done_missed_and_today(page, base_url, gui_db_path):
    idea = make_idea(base_url, "heatmap")
    goal = make_goal(base_url, "walk", idea["id"], weekdays=DAILY)
    backdate_goal(gui_db_path, goal["id"], 3)
    for day in (days_ago(3), days_ago(2)):
        check_off(base_url, goal["id"], day)

    open_view(page, base_url, idea["id"])

    cells = page.locator(".mini-heatmap .heatmap-cell")
    # FIXED_TODAY is a Thursday: 11 full weeks + Mon-Thu, no padding needed
    assert cells.count() == 81
    assert page.locator(".mini-heatmap .heatmap-cell.blank").count() == 0
    assert page.locator('.mini-heatmap .heatmap-cell[data-level="4"]').count() == 2
    assert (
        page.locator('.mini-heatmap .heatmap-cell[data-level="missed"]').count() == 2
    )  # yesterday + today
    assert page.locator(".mini-heatmap .heatmap-cell.today").count() == 1


def test_timeline_shows_goals_stopped_and_done(page, base_url):
    idea = make_idea(base_url, "timeline kinds")
    habit = make_goal(base_url, "old habit", idea["id"], weekdays=DAILY)
    api(base_url, "POST", f"/api/goals/{habit['id']}/stop")
    one_off = make_goal(base_url, "book physio", idea["id"])
    check_off(base_url, one_off["id"])

    open_view(page, base_url, idea["id"])

    events = page.locator(".timeline-what").all_inner_texts()
    assert "goal stopped: old habit" in events
    assert "goal done: book physio" in events


def test_blurring_unchanged_notes_saves_nothing(page, base_url):
    idea = make_idea(base_url, "untouched notes", "same as before")
    open_view(page, base_url, idea["id"])
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)

    page.click("#notes-toggle")
    page.locator("#view-title").click()
    page.wait_for_timeout(300)

    assert patches == []


def test_shift_enter_in_the_title_saves_one_line(page, base_url):
    idea = make_idea(base_url, "one line")
    open_view(page, base_url, idea["id"])

    page.locator("#view-title").press("End")
    page.keyboard.type(" more")
    with idea_save(page):
        page.keyboard.press("Shift+Enter")

    assert get_idea(base_url, idea["id"])["text"] == "one line more"


def test_pasted_line_breaks_in_the_title_become_spaces(page, base_url):
    idea = make_idea(base_url, "paste")
    open_view(page, base_url, idea["id"])

    page.locator("#view-title").fill("first\nsecond\r\nthird")

    assert page.input_value("#view-title") == "first second third"


# ---- when saving fails ----


def _fail_requests(page, method):
    page.route(
        "**/api/**",
        lambda route: (
            route.fulfill(
                status=500, content_type="application/json", body='{"error": "boom"}'
            )
            if route.request.method == method
            else route.continue_()
        ),
    )


def test_failed_idea_save_says_so(page, base_url):
    idea = make_idea(base_url, "save fails")
    open_view(page, base_url, idea["id"])
    _fail_requests(page, "PATCH")

    page.click('#view-status-pills button[data-status="active"]')

    page.wait_for_function(
        "document.getElementById('view-save-state').classList.contains('error')"
    )
    assert page.inner_text("#view-save-state") == "not saved: boom"
    assert get_idea(base_url, idea["id"])["status"] == "inbox"


def test_failed_goal_check_off_says_so(page, base_url):
    idea = make_idea(base_url, "check fails")
    make_goal(base_url, "walk", idea["id"], weekdays=DAILY)
    open_view(page, base_url, idea["id"])
    _fail_requests(page, "PATCH")

    page.locator(".objective .goal-check").click()

    page.wait_for_function(
        "document.getElementById('view-save-state').classList.contains('error')"
    )
    assert page.inner_text("#view-save-state") == "not saved: couldn't update that goal"
    assert page.locator(".objective .goal-check").inner_text() == "[ ]"


def test_failed_delete_stays_on_the_page_and_says_so(page, base_url):
    idea = make_idea(base_url, "delete fails")
    open_view(page, base_url, idea["id"])
    _fail_requests(page, "DELETE")

    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#view-delete")

    page.wait_for_function(
        "document.getElementById('view-save-state').classList.contains('error')"
    )
    assert page.inner_text("#view-save-state") == "not deleted: the server refused"
    assert page.url.endswith(f"/idea.html?id={idea['id']}")


def test_notes_wait_for_a_pause_in_typing_before_saving(page, base_url):
    idea = make_idea(base_url, "debounced", "x")
    open_view(page, base_url, idea["id"])
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)

    page.click("#notes-toggle")
    page.locator("#notes-editor").type("abc")
    page.wait_for_timeout(400)  # well inside the ~1.2s pause it waits for

    assert patches == []


def test_duplicate_field_name_is_refused_not_saved(page, base_url):
    idea = make_idea(base_url, "dupes", fields={"a": "1"})
    open_view(page, base_url, idea["id"])

    page.click("#field-add")
    page.keyboard.type("a")
    page.keyboard.press("Tab")

    page.wait_for_function(
        "document.getElementById('view-save-state').classList.contains('error')"
    )
    assert (
        page.inner_text("#view-save-state")
        == "not saved: two fields have the same name"
    )
    assert get_idea(base_url, idea["id"])["fields"] == {"a": "1"}


def test_unreachable_server_on_load_shows_a_notice(page, base_url):
    idea = make_idea(base_url, "server down")
    page.route("**/overview", lambda route: route.abort())

    page.goto(f"{base_url}/idea.html?id={idea['id']}")

    page.wait_for_selector("#view-notice:not([hidden])")
    assert "couldn't reach the server" in page.inner_text("#view-notice")


def test_unreachable_server_on_check_off_says_so(page, base_url):
    idea = make_idea(base_url, "check offline")
    make_goal(base_url, "walk", idea["id"], weekdays=DAILY)
    open_view(page, base_url, idea["id"])
    page.route("**/api/goals/**", lambda route: route.abort())

    page.locator(".objective .goal-check").click()

    page.wait_for_function(
        "document.getElementById('view-save-state').classList.contains('error')"
    )
    assert page.inner_text("#view-save-state") == "not saved: couldn't reach the server"


def test_unreachable_server_on_delete_says_so(page, base_url):
    idea = make_idea(base_url, "delete offline")
    open_view(page, base_url, idea["id"])
    page.route(
        "**/api/ideas/*",
        lambda route: (
            route.abort() if route.request.method == "DELETE" else route.continue_()
        ),
    )

    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#view-delete")

    page.wait_for_function(
        "document.getElementById('view-save-state').classList.contains('error')"
    )
    assert (
        page.inner_text("#view-save-state") == "not deleted: couldn't reach the server"
    )
    assert page.url.endswith(f"/idea.html?id={idea['id']}")


# ---- theme: follows the board's stored choice ----


def _open_with_stored_theme(page, base_url, theme):
    idea = make_idea(base_url, f"theme {theme}")
    page.goto(base_url + "/")
    if theme is None:
        page.evaluate("localStorage.removeItem('idea-bank-theme')")
    else:
        page.evaluate(f"localStorage.setItem('idea-bank-theme', '{theme}')")
    open_view(page, base_url, idea["id"])
    return page.evaluate("document.documentElement.dataset.theme ?? null")


def test_page_uses_the_stored_light_theme(page, base_url):
    assert _open_with_stored_theme(page, base_url, "light") == "light"


def test_page_defaults_to_dark_with_no_stored_theme(page, base_url):
    assert _open_with_stored_theme(page, base_url, None) == "dark"


def test_page_leaves_the_system_theme_to_the_browser(page, base_url):
    assert _open_with_stored_theme(page, base_url, "system") is None
