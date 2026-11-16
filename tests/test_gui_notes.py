"""Browser tests for markdown notes, in both places notes appear: the full
idea view (idea.html) and the board's detail modal. They cover what can't
run under Node -- sanitizing (DOMPurify), link targets, and the read/edit
toggle. Fixtures (base_url, page) are in conftest.py."""

import pytest

from gui_support import get_idea, make_idea

QUEST_NOTES = "# Quest\nwalk **daily**\n\n- [x] shoes\n- [ ] week 1\n\n[map](https://example.com/route)"
HOSTILE_NOTES = (
    "# evil\n\n"
    "<script>window.__pwned = 'script'</script>\n\n"
    '<img src="x" onerror="window.__pwned = \'img\'">\n\n'
    "[click](javascript:window.__pwned='link')\n\n"
    "<a href=\"javascript:window.__pwned='raw'\">raw</a>\n\n"
    '<iframe src="https://example.com"></iframe>\n\n'
    "<b onclick=\"window.__pwned='click'\">bold</b>"
)

# the full idea view's notes panel
VIEW = "#notes-view"
EDITOR = "#notes-editor"
TOGGLE = "#notes-toggle"


def open_view(page, base_url, idea_id):
    page.goto(f"{base_url}/idea.html?id={idea_id}")
    page.wait_for_selector("#idea-view:not([hidden])")


def open_board_modal(page, base_url, idea_id):
    page.goto(base_url + "/")
    page.keyboard.press("i")
    page.locator(f'.card[data-id="{idea_id}"]').click()
    page.keyboard.press("Enter")
    page.wait_for_selector("#modal-backdrop:not([hidden])")


# ---- sanitizing ----


def test_hostile_notes_run_no_code_and_keep_no_dangerous_markup(page, base_url):
    idea = make_idea(base_url, "hostile", HOSTILE_NOTES)

    open_view(page, base_url, idea["id"])
    page.locator(f"{VIEW} b").click()
    page.wait_for_timeout(300)  # give any injected handler a chance to fire

    assert page.evaluate("window.__pwned") is None
    view = page.locator(VIEW)
    assert view.locator("script, iframe").count() == 0
    attributes = page.evaluate(f"""() => [...document.querySelectorAll('{VIEW} *')]
              .flatMap(el => [...el.attributes].map(a => [a.name, a.value]))""")
    assert not [name for name, _ in attributes if name.startswith("on")]
    assert not [
        v for name, v in attributes if name == "href" and "javascript:" in v.lower()
    ]
    assert view.locator("h3 .md-h-text").inner_text() == "evil"


def test_notes_cannot_add_form_controls_or_element_ids(page, base_url):
    page.goto(base_url + "/")

    html = page.evaluate(
        """() => {
          const div = document.createElement('div');
          div.append(IdeaMarkdown.renderMarkdown(
            '<form action="https://evil.example"><input name="pw"><button formaction="x">go</button></form>' +
            '<select><option>a</option></select><textarea>t</textarea>' +
            '<div id="view-notice" name="n">fake</div>'));
          return div.innerHTML;
        }"""
    )

    for tag in ("<form", "<input", "<button", "<select", "<option", "<textarea"):
        assert tag not in html
    assert " id=" not in html and " name=" not in html
    assert "fake" in html  # the text itself still shows


def test_render_markdown_strips_scripts_and_handlers_directly(page, base_url):
    page.goto(base_url + "/")

    html = page.evaluate("""() => {
          const div = document.createElement('div');
          div.append(IdeaMarkdown.renderMarkdown(
            '<script>x()</script><img src=x onerror=alert(1)><svg onload=alert(1)></svg>'));
          return div.innerHTML;
        }""")

    assert "<script" not in html
    assert "onerror" not in html
    assert "onload" not in html
    assert '<img src="x">' in html


def _sanitized(page, markdown):
    return page.evaluate(
        """(source) => {
          const div = document.createElement('div');
          div.append(IdeaMarkdown.renderMarkdown(source));
          return div.innerHTML;
        }""",
        markdown,
    )


def test_notes_cannot_restyle_the_page(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(
        page,
        '<div style="position:fixed;inset:0" class="modal-backdrop panel">cover</div>'
        '<style>@import url(https://evil.example/x.css); body{display:none}</style>',
    )

    assert "style" not in html
    assert "class=" not in html
    assert "cover" in html


def test_notes_keep_the_renderers_own_classes(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(page, "# Title\n\n- [x] done task")

    assert 'class="md-h md-h1"' in html
    assert 'class="md-h-text"' in html
    assert 'class="md-task-mark done"' in html
    assert 'class="sr-only"' in html


def test_notes_keep_callout_and_data_block_classes(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(page, "> [!ALARM] late\n> fix it\n\n```schedule\nday | A\nMon | 2\n```")

    for kept in [
        'class="md-callout md-tone-flame"',
        'class="md-callout-kind"',
        'class="md-callout-text"',
        'class="nb-block nb-schedule"',
        'class="nb-heat"',
    ]:
        assert kept in html


def test_a_note_cannot_borrow_renderer_classes_for_other_markup(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(page, '<div class="nb-block modal-backdrop">x</div>')

    assert 'class="nb-block"' in html
    assert "modal-backdrop" not in html


def test_notes_cannot_set_a_background_image(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(page, '<table background="https://evil.example/bg.png"><tr><td>x</td></tr></table>')

    assert "background" not in html
    assert "evil" not in html


def _bar_styles(page, markdown):
    return page.evaluate(
        """(source) => {
          const div = document.createElement("div");
          div.append(IdeaMarkdown.renderMarkdown(source, "2026-11-16"));
          return {
            bars: [...div.querySelectorAll(".nb-pos")].map((n) => [n.style.left, n.style.width]),
            cols: [...div.querySelectorAll(".nb-schedule")].map((n) => n.style.getPropertyValue("--nb-cols")),
          };
        }""",
        markdown,
    )


def test_data_block_bars_are_placed_from_their_data(page, base_url):
    page.goto(base_url + "/")

    styles = _bar_styles(page, "```phases\nP1 | 2026-11-09 | 2026-11-15\nP2 | 2026-11-16 | 2026-11-22\n```")

    segments = styles["bars"][:2]
    assert segments == [["0%", "50%"], ["50%", "50%"]]


def test_a_schedule_sets_its_column_count(page, base_url):
    page.goto(base_url + "/")

    styles = _bar_styles(page, "```schedule\nday | A | B | C\nMon | 1 | 2 | 3\n```")

    assert styles["cols"] == ["3"]


def test_raw_html_bar_positions_stay_inside_their_block(page, base_url):
    page.goto(base_url + "/")

    styles = _bar_styles(
        page,
        '<span class="nb-pos" data-left="-50" data-width="900"></span>'
        '<span class="nb-pos" data-left="junk"></span>'
        '<div class="nb-schedule" data-cols="500"></div><div class="nb-schedule" data-cols="0"></div>',
    )

    assert styles["bars"] == [["0%", "100%"], ["0%", ""]]
    assert styles["cols"] == ["24", "1"]


# ---- section task counts ----


def _task_counts(page, markdown):
    return page.evaluate(
        """(source) => {
          const div = document.createElement("div");
          div.append(IdeaMarkdown.renderMarkdown(source));
          return [...div.querySelectorAll(".md-h")].map((h) => {
            const count = h.querySelector(".md-h-count");
            return count ? [count.textContent, count.classList.contains("complete")] : null;
          });
        }""",
        markdown,
    )


def test_each_heading_counts_the_tasks_under_it(page, base_url):
    page.goto(base_url + "/")

    counts = _task_counts(
        page, "# One\n- [x] a\n- [ ] b\n- [ ] c\n\n# Two\n- [x] d\n- [x] e\n\n# Three\nno tasks"
    )

    assert counts == [["1/3", False], ["✓ 2/2", True], None]


def test_a_sub_heading_starts_its_own_count(page, base_url):
    page.goto(base_url + "/")

    counts = _task_counts(page, "# Top\n- [x] a\n\n### Sub\n- [ ] b")

    assert counts == [["✓ 1/1", True], ["0/1", False]]


def test_tasks_before_the_first_heading_and_nested_tasks(page, base_url):
    page.goto(base_url + "/")

    counts = _task_counts(page, "- [ ] loose\n\n# Plan\n- [x] a\n  - [ ] nested")

    assert counts == [["1/2", False]]


def test_task_count_is_shown_in_the_view_with_a_readable_title(page, base_url):
    idea = make_idea(base_url, "counted", "## Setup\n- [x] shoes\n- [ ] route")

    open_view(page, base_url, idea["id"])

    count = page.locator(f"{VIEW} .md-h-count")
    assert count.inner_text() == "1/2"
    assert count.get_attribute("title") == "1 of 2 tasks done"


def test_notes_load_nothing_from_other_sites(page, base_url):
    page.goto(base_url + "/")
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "example" in r.url else None)

    html = _sanitized(
        page,
        "![a](https://evil.example/a.png) ![b](//evil.example/b.png) ![c](http://evil.example/c.png)\n\n"
        '<img src="x.png" srcset="https://evil.example/s.png 2x">'
        '<video src="https://evil.example/v.mp4" poster="https://evil.example/p.png"></video>'
        '<audio src="https://evil.example/a.mp3"></audio>'
        '<svg><image href="https://evil.example/i.png"/><use href="https://evil.example/u.svg#x"/></svg>',
    )
    page.wait_for_timeout(300)

    assert "evil.example" not in html
    assert requests == []


def test_notes_load_nothing_via_url_tricks(page, base_url):
    page.goto(base_url + "/")
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "evil" in r.url else None)

    html = _sanitized(
        page,
        '<img src="/\\evil.example/a.png"><img src="\\\\evil.example/b.png">'
        '<img src="/\t/evil.example/c.png"><img src="ht\ttps://evil.example/d.png">'
        '<svg><filter><feImage href="https://evil.example/e.png"></feImage></filter></svg>',
    )
    page.wait_for_timeout(300)

    assert requests == []
    assert "evil" not in html


def test_svg_paint_and_effects_cannot_point_at_other_files(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(
        page,
        '<svg><rect fill="url(https://evil.example/p.svg#g)" filter="url(\'//evil.example/f.svg#f\')"'
        ' mask="url( /static/m.svg#m)" stroke="url(#local)"/></svg>',
    )

    assert "evil" not in html
    assert "m.svg" not in html
    assert 'stroke="url(#local)"' in html


def test_other_svg_elements_cannot_link_to_other_files(page, base_url):
    page.goto(base_url + "/")
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "evil" in r.url else None)

    html = page.evaluate("""() => {
          const div = document.createElement('div');
          document.body.append(div);  // attached, so the browser would really load them
          div.append(IdeaMarkdown.renderMarkdown(
            '<svg><defs><pattern id="p" href="https://evil.example/p.svg#x"/>' +
            '<linearGradient xlink:href="https://evil.example/g.svg#g"/></defs>' +
            '<text><textPath href="https://evil.example/t.svg#t">t</textPath></text>' +
            '<linearGradient xlink:href="#local"/></svg>'));
          return div.innerHTML;
        }""")
    page.wait_for_timeout(300)

    assert "evil" not in html
    assert requests == []
    assert 'xlink:href="#local"' in html


def test_embedded_images_must_be_images(page, base_url):
    page.goto(base_url + "/")

    html = _sanitized(page, '<img src="data:text/html,<b>x</b>">')

    assert "src=" not in html


def test_notes_keep_local_and_embedded_images(page, base_url):
    page.goto(base_url + "/")
    pixel = "data:image/png;base64,iVBORw0KGgo="

    html = _sanitized(page, f"![local](/static/x.png) ![rel](img/y.png) ![inline]({pixel})")

    assert 'src="/static/x.png"' in html
    assert 'src="img/y.png"' in html
    assert f'src="{pixel}"' in html


# ---- links ----


def test_links_open_in_a_new_window_except_in_page_anchors(page, base_url):
    page.goto(base_url + "/")

    links = page.evaluate("""() => {
          const div = document.createElement('div');
          div.append(IdeaMarkdown.renderMarkdown(
            '[web](https://example.com) [mail](mailto:a@b.c) [here](#sec)\\n\\n' +
            '<svg><a href="https://svg.example"><text>t</text></a></svg>'));
          return [...div.querySelectorAll('a')].map(
            a => [a.getAttribute('href'), a.getAttribute('target'), a.getAttribute('rel')]);
        }""")

    assert links == [
        ["https://example.com", "_blank", "noopener noreferrer"],
        ["mailto:a@b.c", "_blank", "noopener noreferrer"],
        ["#sec", None, None],
        ["https://svg.example", "_blank", "noopener noreferrer"],
    ]


def test_svg_links_written_with_xlink_also_open_in_a_new_window(page, base_url):
    page.goto(base_url + "/")

    link = page.evaluate("""() => {
          const div = document.createElement('div');
          div.append(IdeaMarkdown.renderMarkdown(
            '<svg><a xlink:href="https://x.example"><text>t</text></a></svg>'));
          const a = div.querySelector('a');
          return [a.getAttribute('xlink:href'), a.getAttribute('target'), a.getAttribute('rel')];
        }""")

    assert link == ["https://x.example", "_blank", "noopener noreferrer"]


# ---- read/edit toggle (full idea view) ----


def test_notes_open_in_rendered_read_view(page, base_url):
    idea = make_idea(base_url, "quest", QUEST_NOTES)

    open_view(page, base_url, idea["id"])

    assert page.is_visible(VIEW)
    assert page.is_hidden(EDITOR)
    assert page.inner_text(TOGGLE) == "edit"
    assert page.get_attribute(TOGGLE, "aria-pressed") == "false"
    view = page.locator(VIEW)
    assert view.locator("h3 .md-h-text").inner_text() == "Quest"
    assert view.locator("strong").inner_text() == "daily"
    assert view.locator(".md-task-mark").all_inner_texts() == ["[x]", "[ ]"]
    assert page.errors == []


def test_empty_notes_open_straight_into_the_editor(page, base_url):
    idea = make_idea(base_url, "no notes")

    open_view(page, base_url, idea["id"])

    assert page.is_visible(EDITOR)
    assert page.is_hidden(VIEW)
    assert page.inner_text(TOGGLE) == "preview"
    assert page.get_attribute(TOGGLE, "aria-pressed") == "true"
    assert page.evaluate("document.activeElement.id") != "notes-editor"


def test_whitespace_only_notes_count_as_empty(page, base_url):
    idea = make_idea(base_url, "blank notes", "  \n\n ")

    open_view(page, base_url, idea["id"])

    assert page.is_visible(EDITOR)


def test_edit_then_preview_renders_the_edited_text(page, base_url):
    idea = make_idea(base_url, "editable", QUEST_NOTES)
    open_view(page, base_url, idea["id"])

    page.click(TOGGLE)
    assert page.is_visible(EDITOR)
    assert page.input_value(EDITOR) == QUEST_NOTES
    page.fill(EDITOR, "## Renamed")
    page.click(TOGGLE)

    assert page.is_hidden(EDITOR)
    assert page.locator(f"{VIEW} h4 .md-h-text").inner_text() == "Renamed"
    assert page.inner_text(TOGGLE) == "edit"


def test_double_click_enters_edit_but_not_on_a_link(page, base_url):
    idea = make_idea(base_url, "dblclick", QUEST_NOTES)
    open_view(page, base_url, idea["id"])

    # a synthetic dblclick: a real one would follow the link first
    page.locator(f"{VIEW} a").dispatch_event("dblclick")
    assert page.is_visible(VIEW)

    page.locator(f"{VIEW} h3").dblclick()
    assert page.is_visible(EDITOR)
    assert page.evaluate("document.activeElement.id") == "notes-editor"


def test_editor_grows_with_long_notes(page, base_url):
    long_notes = "\n".join(f"- line {n}" for n in range(40))
    idea = make_idea(base_url, "long", long_notes)
    open_view(page, base_url, idea["id"])

    page.click(TOGGLE)

    rows_tall = page.evaluate(
        "(() => { const t = document.getElementById('notes-editor');"
        " return t.clientHeight / parseFloat(getComputedStyle(t).lineHeight); })()"
    )
    assert rows_tall > 10


def test_editor_stops_growing_at_most_of_the_window(page, base_url):
    long_notes = "\n".join(f"- line {n}" for n in range(300))
    idea = make_idea(base_url, "very long", long_notes)
    open_view(page, base_url, idea["id"])

    page.click(TOGGLE)

    height, window_height = page.evaluate(
        "[document.getElementById('notes-editor').getBoundingClientRect().height, window.innerHeight]"
    )
    assert height == pytest.approx(window_height * 0.6, abs=1)


def test_editor_keeps_growing_while_typing(page, base_url):
    idea = make_idea(base_url, "growing")
    open_view(page, base_url, idea["id"])  # empty notes: editor already open
    start_height = page.evaluate("document.getElementById('notes-editor').clientHeight")

    page.locator(EDITOR).type("\n".join(f"line {n}" for n in range(15)))

    assert page.evaluate("document.getElementById('notes-editor').clientHeight") > start_height


# ---- board modal ----


def test_board_modal_renders_notes_and_saves_edits(page, base_url):
    idea = make_idea(base_url, "board quest", QUEST_NOTES)
    open_board_modal(page, base_url, idea["id"])

    assert page.locator("#modal-notes-view h3 .md-h-text").inner_text() == "Quest"
    page.click("#modal-notes-toggle")
    page.fill("#modal-notes", "# Updated\nline two")
    with page.expect_response(lambda r: r.request.method == "PATCH"):
        page.click("#modal-done")

    page.wait_for_selector("#modal-backdrop", state="hidden")
    assert get_idea(base_url, idea["id"])["notes"] == "# Updated\nline two"


def test_board_modal_status_change_keeps_edit_mode(page, base_url):
    idea = make_idea(base_url, "status while editing", QUEST_NOTES)
    open_board_modal(page, base_url, idea["id"])

    page.click("#modal-notes-toggle")
    page.fill("#modal-notes", "unsaved draft")
    page.locator('#modal-status-pills button[data-status="queued"]').click()

    assert page.is_visible("#modal-notes")
    assert page.input_value("#modal-notes") == "unsaved draft"


def test_board_modal_shows_each_ideas_own_notes(page, base_url):
    first = make_idea(base_url, "first", "# First notes")
    second = make_idea(base_url, "second")

    open_board_modal(page, base_url, first["id"])
    page.keyboard.press("Escape")
    page.locator(f'.card[data-id="{second["id"]}"]').click()
    page.keyboard.press("Enter")

    assert page.is_visible("#modal-notes")
    assert page.input_value("#modal-notes") == ""


def test_board_modal_first_idea_notes_render_before_switching(page, base_url):
    first = make_idea(base_url, "first rendered", "# First notes")

    open_board_modal(page, base_url, first["id"])

    assert page.locator("#modal-notes-view h3 .md-h-text").inner_text() == "First notes"


def test_board_modal_clearing_notes_saves_them_as_empty(page, base_url):
    idea = make_idea(base_url, "modal clear", "something")
    open_board_modal(page, base_url, idea["id"])

    page.click("#modal-notes-toggle")
    page.fill("#modal-notes", "")
    with page.expect_response(lambda r: r.request.method == "PATCH"):
        page.click("#modal-done")

    assert get_idea(base_url, idea["id"])["notes"] is None


def test_board_modal_done_keeps_edits_saved_in_the_full_view(page, base_url):
    idea = make_idea(base_url, "original", fields={"k": "v"})
    open_board_modal(page, base_url, idea["id"])
    with page.expect_popup() as popup_info:
        page.click("#modal-popout")
    popup = popup_info.value
    popup.wait_for_selector("#idea-view:not([hidden])")
    popup.fill("#view-title", "renamed in full view")
    with popup.expect_response(lambda r: r.request.method == "PATCH"):
        popup.keyboard.press("Enter")

    page.bring_to_front()
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)
    page.click("#modal-done")  # nothing changed in the modal itself
    page.wait_for_timeout(300)  # time for a wrongly-sent save to go out

    assert patches == []
    saved = get_idea(base_url, idea["id"])
    assert saved["text"] == "renamed in full view"
    assert saved["fields"] == {"k": "v"}


def test_board_modal_done_sends_only_what_changed(page, base_url):
    idea = make_idea(base_url, "partial", fields={"k": "v"})
    open_board_modal(page, base_url, idea["id"])
    page.locator('#modal-status-pills button[data-status="queued"]').click()

    with page.expect_request(lambda r: r.method == "PATCH") as request_info:
        page.click("#modal-done")

    assert request_info.value.post_data_json == {"status": "queued"}


def test_board_modal_full_view_button_opens_the_idea_page(page, base_url):
    idea = make_idea(base_url, "pop me out", QUEST_NOTES)
    open_board_modal(page, base_url, idea["id"])

    with page.expect_popup() as popup_info:
        page.click("#modal-popout")
    popup = popup_info.value
    popup.wait_for_selector("#idea-view:not([hidden])")

    assert popup.url.endswith(f"/idea.html?id={idea['id']}")
    assert popup.input_value("#view-title") == "pop me out"
