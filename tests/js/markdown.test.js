// Tests for static/markdown.js's marked configuration, run with Node's
// built-in test runner (`node --test`) from tests/test_markdown_js.py.
// They cover only what this app changes about marked -- heading levels,
// task glyphs, line breaks, callouts, data blocks -- not marked's own
// markdown parsing. The data blocks' drawing is in note-blocks.test.js.
// Sanitizing (DOMPurify) needs a browser DOM, so it isn't exercised here;
// markdownToHtml is the unsanitized half that renderMarkdown sanitizes.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { markdownToHtml } = require(path.join(__dirname, "..", "..", "static", "markdown.js"));

const headingText = (html) => `<span class="md-h-text">${html}</span>`;
const doneMark =
  '<span class="md-task-mark done" aria-hidden="true">[x]</span><span class="sr-only">done: </span>';
const todoMark = '<span class="md-task-mark" aria-hidden="true">[ ]</span><span class="sr-only">to do: </span>';

test("empty, null and undefined notes render to nothing", () => {
  assert.equal(markdownToHtml(""), "");
  assert.equal(markdownToHtml(null), "");
  assert.equal(markdownToHtml(undefined), "");
});

test("a level-1 heading renders as h3, without its # marker", () => {
  assert.equal(markdownToHtml("# Quest"), `<h3 class="md-h md-h1">${headingText("Quest")}</h3>\n`);
});

test("heading levels shift down by two", () => {
  assert.equal(markdownToHtml("## Phase"), `<h4 class="md-h md-h2">${headingText("Phase")}</h4>\n`);
  assert.equal(markdownToHtml("### Rules"), `<h5 class="md-h md-h3">${headingText("Rules")}</h5>\n`);
});

test("levels 4 to 6 all cap at h6 but keep their own class", () => {
  for (const depth of [4, 5, 6]) {
    assert.equal(
      markdownToHtml(`${"#".repeat(depth)} deep`),
      `<h6 class="md-h md-h${depth}">${headingText("deep")}</h6>\n`
    );
  }
});

test("inline markdown inside a heading is still rendered", () => {
  assert.equal(
    markdownToHtml("# **Bold** `code`"),
    `<h3 class="md-h md-h1">${headingText("<strong>Bold</strong> <code>code</code>")}</h3>\n`
  );
});

test("task items render [x]/[ ] glyphs with screen-reader text, not checkboxes", () => {
  const html = markdownToHtml("- [x] done\n- [ ] todo");
  assert.equal(html, `<ul>\n<li>${doneMark}done</li>\n<li>${todoMark}todo</li>\n</ul>\n`);
  assert.ok(!html.includes("<input"));
});

test("an upper-case X also marks a task done", () => {
  assert.ok(markdownToHtml("- [X] done").includes(doneMark));
});

test("a plain bullet item gets no task glyph", () => {
  assert.equal(markdownToHtml("- item"), "<ul>\n<li>item</li>\n</ul>\n");
});

test("a single newline is kept as a line break", () => {
  assert.equal(markdownToHtml("one\ntwo"), "<p>one<br>two</p>\n");
});

test("a blank line still separates paragraphs", () => {
  assert.equal(markdownToHtml("one\n\ntwo"), "<p>one</p>\n<p>two</p>\n");
});

test("github-style tables are enabled", () => {
  const html = markdownToHtml("| a | b |\n|---|--:|\n| 1 | 2 |");
  assert.ok(html.startsWith("<table>"));
  assert.ok(html.includes('<td align="right">2</td>'));
});

test("raw html passes through unsanitized -- which is why renderMarkdown sanitizes", () => {
  assert.ok(markdownToHtml("<script>x()</script>").includes("<script>x()</script>"));
});

test("a plain > quote is still a quote", () => {
  assert.equal(markdownToHtml("> quoted"), "<blockquote>\n<p>quoted</p>\n</blockquote>\n");
});

// ---- callouts ----

const callout = ({ tone, glyph, kind, title = "" }, body) =>
  `<div class="md-callout md-tone-${tone}"><div class="md-callout-title">` +
  `<span class="md-callout-kind"><span aria-hidden="true">${glyph} </span>${kind}</span>` +
  (title ? `<span class="md-callout-text">${title}</span>` : "") +
  `</div>${body}</div>\n`;

test("a quote starting with [!ALARM] and a title is a flame callout card", () => {
  assert.equal(
    markdownToHtml("> [!ALARM] If you fall behind\n> skip the extras"),
    callout({ tone: "flame", glyph: "⚠", kind: "ALARM", title: "If you fall behind" }, "<p>skip the extras</p>\n")
  );
});

test("each known kind picks its own tone and symbol, in any case", () => {
  const expected = {
    warning: ["flame", "⚠"], caution: ["flame", "⚠"], important: ["flame", "!"],
    note: ["cobalt", "ℹ"], info: ["cobalt", "ℹ"],
    tip: ["moss", "✦"], goal: ["moss", "⚑"], win: ["moss", "★"],
  };
  for (const [kind, [tone, glyph]] of Object.entries(expected)) {
    for (const typed of [kind, kind.toUpperCase()]) {
      const html = markdownToHtml(`> [!${typed}]\n> x`);
      assert.ok(html.startsWith(`<div class="md-callout md-tone-${tone}">`), `${typed}: ${html}`);
      assert.ok(html.includes(`<span aria-hidden="true">${glyph} </span>${kind.toUpperCase()}</span>`), typed);
    }
  }
});

test("an unknown kind is an ink callout with a plain diamond, named as typed", () => {
  assert.equal(
    markdownToHtml("> [!Reminder-2]\n> call"),
    callout({ tone: "ink", glyph: "◆", kind: "REMINDER-2" }, "<p>call</p>\n")
  );
});

test("a callout without a title has no title text", () => {
  assert.ok(!markdownToHtml("> [!NOTE]\n> body").includes("md-callout-text"));
});

test("a callout's title and body are rendered as markdown", () => {
  assert.equal(
    markdownToHtml("> [!TIP] use **this**\n> - one\n> - two"),
    callout({ tone: "moss", glyph: "✦", kind: "TIP", title: "use <strong>this</strong>" }, "<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n")
  );
});

test("a callout ends at the first line that isn't quoted", () => {
  assert.equal(
    markdownToHtml("> [!NOTE]\n> inside\noutside"),
    callout({ tone: "cobalt", glyph: "ℹ", kind: "NOTE" }, "<p>inside</p>\n") + "<p>outside</p>\n"
  );
});

test("a callout can follow a paragraph directly", () => {
  assert.equal(
    markdownToHtml("intro\n> [!WIN] shipped"),
    "<p>intro</p>\n" + callout({ tone: "moss", glyph: "★", kind: "WIN", title: "shipped" }, "")
  );
});

test("a callout may be indented up to three spaces, like any quote", () => {
  assert.ok(markdownToHtml("   > [!NOTE] x").startsWith('<div class="md-callout md-tone-cobalt">'));
});

test("a callout's title text is escaped", () => {
  assert.ok(markdownToHtml("> [!NOTE] a & b").includes('<span class="md-callout-text">a &amp; b</span>'));
});

test("[!WORD] later in a quote, or not at its start, is just a quote", () => {
  assert.ok(markdownToHtml("> first\n> [!NOTE] second").startsWith("<blockquote>"));
  assert.equal(markdownToHtml("see [!NOTE] here"), "<p>see [!NOTE] here</p>\n");
  assert.ok(markdownToHtml("> [!1abc]\n> x").startsWith("<blockquote>"));
});

test("a [!NOTE] quote inside indented code stays code", () => {
  assert.equal(markdownToHtml("x\n\n    > [!NOTE] y"), "<p>x</p>\n<pre><code>&gt; [!NOTE] y\n</code></pre>\n");
});

// ---- data blocks: which fenced blocks are drawn ----

const TODAY = "2026-11-16";
const SCHEDULE = "day | DSA\nMon | 2";

test("a block tagged schedule, phases or targets is drawn, in any case", () => {
  assert.ok(markdownToHtml("```schedule\n" + SCHEDULE + "\n```", TODAY).startsWith('<div class="nb-block nb-schedule"'));
  assert.ok(markdownToHtml("```Schedule\n" + SCHEDULE + "\n```", TODAY).startsWith('<div class="nb-block nb-schedule"'));
  assert.ok(markdownToHtml("```phases\nP1 2026-11-09 2026-11-22\n```", TODAY).startsWith('<div class="nb-block nb-phases"'));
  assert.ok(markdownToHtml("```targets\nW1 | 2026-11-09 | 8\n```", TODAY).startsWith('<div class="nb-block nb-targets"'));
});

test("a block with any other tag, or none, stays code", () => {
  assert.equal(markdownToHtml("```sh\nidea list\n```"), '<pre><code class="language-sh">idea list\n</code></pre>\n');
  assert.equal(markdownToHtml("```\n" + SCHEDULE + "\n```"), `<pre><code>${SCHEDULE}\n</code></pre>\n`);
});

test("a tagged block that doesn't fit its format stays code, showing what was typed", () => {
  assert.equal(
    markdownToHtml("```schedule\nday | DSA\nMon | lots\n```", TODAY),
    '<pre><code class="language-schedule">day | DSA\nMon | lots\n</code></pre>\n'
  );
});

test("the date passed in is where blocks mark today", () => {
  const block = "```phases\nP1 2026-11-09 2026-11-15\nP2 2026-11-16 2026-11-22\n```";
  assert.ok(markdownToHtml(block, "2026-11-10").includes('<li class="nb-phase nb-now"><span class="nb-phase-head"><span class="nb-glyph" aria-hidden="true">▶</span><span class="nb-name">P1</span>'));
  assert.ok(markdownToHtml(block, "2026-11-16").includes('<li class="nb-phase nb-now"><span class="nb-phase-head"><span class="nb-glyph" aria-hidden="true">▶</span><span class="nb-name">P2</span>'));
});
