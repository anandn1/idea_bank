// Tests for static/markdown.js's marked configuration, run with Node's
// built-in test runner (`node --test`) from tests/test_markdown_js.py.
// They cover only what this app changes about marked -- heading levels,
// task glyphs, line breaks -- not marked's own markdown parsing.
// Sanitizing (DOMPurify) needs a browser DOM, so it isn't exercised here;
// markdownToHtml is the unsanitized half that renderMarkdown sanitizes.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { markdownToHtml } = require(path.join(__dirname, "..", "..", "static", "markdown.js"));

const headingMarker = (hashes) => `<span class="md-h-mark" aria-hidden="true">${hashes} </span>`;
const doneMark =
  '<span class="md-task-mark done" aria-hidden="true">[x]</span><span class="sr-only">done: </span>';
const todoMark = '<span class="md-task-mark" aria-hidden="true">[ ]</span><span class="sr-only">to do: </span>';

test("empty, null and undefined notes render to nothing", () => {
  assert.equal(markdownToHtml(""), "");
  assert.equal(markdownToHtml(null), "");
  assert.equal(markdownToHtml(undefined), "");
});

test("a level-1 heading renders as h3 with a dim # marker", () => {
  assert.equal(markdownToHtml("# Quest"), `<h3 class="md-h md-h1">${headingMarker("#")}Quest</h3>\n`);
});

test("heading levels shift down by two", () => {
  assert.equal(markdownToHtml("## Phase"), `<h4 class="md-h md-h2">${headingMarker("##")}Phase</h4>\n`);
  assert.equal(markdownToHtml("### Rules"), `<h5 class="md-h md-h3">${headingMarker("###")}Rules</h5>\n`);
});

test("levels 4 to 6 all cap at h6 but keep their own marker and class", () => {
  for (const depth of [4, 5, 6]) {
    const hashes = "#".repeat(depth);
    assert.equal(
      markdownToHtml(`${hashes} deep`),
      `<h6 class="md-h md-h${depth}">${headingMarker(hashes)}deep</h6>\n`
    );
  }
});

test("inline markdown inside a heading is still rendered", () => {
  assert.equal(
    markdownToHtml("# **Bold** `code`"),
    `<h3 class="md-h md-h1">${headingMarker("#")}<strong>Bold</strong> <code>code</code></h3>\n`
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
