// Tests for static/note-blocks.js: how ```schedule, ```phases and
// ```targets blocks are read and drawn, run with Node's built-in test
// runner from tests/test_markdown_js.py. Each renderer returns HTML, or null
// when the text doesn't fit (markdown.js then shows the block as code).
// Today is pinned to Monday 2026-11-16 unless a test says otherwise.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { renderers, calloutStyle, dayNumber } = require(path.join(__dirname, "..", "..", "static", "note-blocks.js"));
const { schedule, phases, targets } = renderers;

const MONDAY = "2026-11-16";

// The text of every element with `className` (exact class token), in order.
function textsOf(html, className) {
  const pattern = new RegExp(`<(\\w+) class="(?:[^"]* )?${className}(?: [^"]*)?"[^>]*>(.*?)</\\1>`, "g");
  return [...html.matchAll(pattern)].map((match) => match[2].replace(/<[^>]+>/g, ""));
}

function attrsOf(html, className, attr) {
  const pattern = new RegExp(`class="(?:[^"]* )?${className}(?: [^"]*)?"[^>]*?${attr}="([^"]*)"`, "g");
  return [...html.matchAll(pattern)].map((match) => match[1]);
}

// ---- dayNumber ----

test("dayNumber counts whole days since 1970 for a real date", () => {
  assert.equal(dayNumber("1970-01-01"), 0);
  assert.equal(dayNumber("1970-01-02"), 1);
  assert.equal(dayNumber("2026-11-16") - dayNumber("2026-11-09"), 7);
});

test("dayNumber refuses impossible or badly written dates", () => {
  for (const bad of ["2026-02-30", "2026-13-01", "2026-00-10", "2026-1-5", "16/11/2026", "", "2026-11-16x"]) {
    assert.equal(dayNumber(bad), null, bad);
  }
  assert.equal(dayNumber("2028-02-29"), dayNumber("2028-02-28") + 1); // leap day
});

test("dayNumber keeps years before 100 as typed, not as 19xx", () => {
  assert.notEqual(dayNumber("0050-01-01"), dayNumber("1950-01-01"));
  assert.equal(dayNumber("0050-01-02") - dayNumber("0050-01-01"), 1);
});

// ---- schedule ----

const WEEK = "day | DSA | Apply\nMon | 2 | -\nTue | 1 | 1.5\nSun |   | 0.5";

test("a schedule is a grid with one column per activity", () => {
  const html = schedule(WEEK, MONDAY);
  assert.ok(html.startsWith('<div class="nb-block nb-schedule" data-cols="2">'));
  assert.deepEqual(textsOf(html, "nb-sched-col").slice(0, 2), ["DSA", "Apply"]);
  assert.deepEqual(textsOf(html, "nb-name"), ["Mon", "Tue", "Sun"]);
});

test("each cell shows its hours, blank for none, with a tooltip naming the column", () => {
  const html = schedule(WEEK, MONDAY);
  assert.deepEqual(textsOf(html, "nb-heat"), ["2", "", "1", "1.5", "", "0.5"]);
  assert.deepEqual(attrsOf(html, "nb-heat", "title"), [
    "DSA: 2h", "Apply: none", "DSA: 1h", "Apply: 1.5h", "DSA: none", "Apply: 0.5h",
  ]);
});

test("heat goes from 0 (none) to 4 (the busiest cell), rounding up", () => {
  // max 2: 2 -> 4, 1 -> 2, 1.5 -> 3, 0.5 -> 1
  assert.deepEqual(attrsOf(schedule(WEEK, MONDAY), "nb-heat", "data-level"), ["4", "0", "2", "3", "0", "1"]);
});

test("a cell between levels rounds up to the next one", () => {
  // max 3: 1 is 1.33 of 4 levels -> 2, 2 is 2.67 -> 3
  assert.deepEqual(attrsOf(schedule("day | A\nMon | 3\nTue | 1\nWed | 2", MONDAY), "nb-heat", "data-level"), ["4", "2", "3"]);
});

test("row, column and grand totals are worked out from the cells", () => {
  const html = schedule(WEEK, MONDAY);
  assert.deepEqual(textsOf(html, "nb-sched-sum"), ["Σ", "2h", "2.5h", "0.5h", "5h"]);
  assert.deepEqual(textsOf(html, "nb-sched-col").slice(2), ["3h", "2h"]);
  assert.ok(html.includes('<span class="nb-sched-label">Σ total</span>'));
});

test("a typed Total row is ignored, so totals can't disagree with the rows", () => {
  const html = schedule("day | DSA\nMon | 2\nTotal | 99\nTOTAL | 5\nTotal (week) | 7", MONDAY);
  assert.deepEqual(textsOf(html, "nb-name"), ["Mon"]);
  assert.deepEqual(textsOf(html, "nb-sched-sum"), ["Σ", "2h", "2h"]);
});

test("decimal totals are rounded to two places", () => {
  assert.deepEqual(textsOf(schedule("day | A\nMon | 0.1\nTue | 0.2", MONDAY), "nb-sched-sum").at(-1), "0.3h");
});

test("columns can be lined up with two or more spaces or tabs instead of pipes", () => {
  const piped = schedule("day | DSA | Skill\nMon | 2 | 1", MONDAY);
  assert.equal(schedule("day   DSA   Skill\nMon   2     1", MONDAY), piped);
  assert.equal(schedule("day\tDSA\tSkill\nMon\t2\t1", MONDAY), piped);
  assert.equal(schedule("| day | DSA | Skill |\n| Mon | 2 | 1 |", MONDAY), piped);
});

test("a single space stays inside a cell", () => {
  assert.deepEqual(textsOf(schedule("day   DSA\nMon morning   2", MONDAY), "nb-name"), ["Mon morning"]);
  assert.deepEqual(textsOf(targets("Week 1   2026-11-09   8", MONDAY), "nb-name"), ["Week 1"]);
});

test("a short row counts its missing cells as no time", () => {
  assert.deepEqual(textsOf(schedule("day | A | B\nMon | 2", MONDAY), "nb-heat"), ["2", ""]);
});

test("today's weekday row is marked, whether written short, long or with an aside", () => {
  for (const label of ["Mon", "monday", "MON (mock day)", "Mon(early)"]) {
    const html = schedule(`day | A\nSun | 1\n${label} | 2`, MONDAY);
    assert.equal((html.match(/nb-now/g) || []).length, 1, label);
    assert.ok(html.includes('<div class="nb-sched-row nb-now"><span class="nb-sched-label"><span class="nb-glyph" aria-hidden="true">▶</span>'), label);
  }
});

test("each weekday is matched to its own date", () => {
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const grid = "day | A\n" + days.map((day) => `${day} | 1`).join("\n");
  days.forEach((day, offset) => {
    const html = schedule(grid, `2026-11-${String(15 + offset).padStart(2, "0")}`); // Nov 15 is a Sunday
    assert.match(html, new RegExp(`nb-now"><span class="nb-sched-label"><span class="nb-glyph" aria-hidden="true">▶</span><span class="nb-name">${day}<`), day);
  });
});

test("a row merely starting with Total is a normal row", () => {
  assert.deepEqual(textsOf(schedule("day | A\nTotally free | 1\nTotals | 2", MONDAY), "nb-name"), ["Totally free", "Totals"]);
});

test("a label that is only an aside is the name itself", () => {
  const html = schedule("day | A\n(spare) | 2", MONDAY);
  assert.deepEqual(textsOf(html, "nb-name"), ["(spare)"]);
  assert.ok(!html.includes("nb-aside"));
});

test("rows that only look like a weekday, or no valid today, mark nothing", () => {
  assert.ok(!schedule("day | A\nMonth | 1\nMo | 2\nweekend | 3", MONDAY).includes("nb-now"));
  assert.ok(!schedule("day | A\nMon | 1", "not a date").includes("nb-now"));
});

test("a row label's trailing (aside) is set apart from its name", () => {
  const html = schedule("day | A\nSat (first 1.5h = mock) | 4", MONDAY);
  assert.ok(html.includes('<span class="nb-name">Sat</span><span class="nb-aside">(first 1.5h = mock)</span>'));
});

test("names and headers are escaped", () => {
  const html = schedule('d<x> | "A"&B\n<b>Mon</b> | 1', MONDAY);
  assert.ok(html.includes("d&lt;x&gt;"));
  assert.ok(html.includes("&quot;A&quot;&amp;B"));
  assert.ok(html.includes("&lt;b&gt;Mon&lt;/b&gt;"));
  assert.ok(!html.includes("<b>"));
  assert.ok(attrsOf(html, "nb-heat", "title")[0] === "&quot;A&quot;&amp;B: 1h");
});

test("a schedule that doesn't fit the format is refused", () => {
  for (const bad of [
    "",
    "day | DSA", // header only
    "day\nMon", // no activity columns
    "day | DSA\nMon | two", // not a number
    "day | DSA\nMon | -2", // negative
    "day | DSA\nMon | 1 | 2", // more cells than columns
    "day | DSA\nTotal | 3", // only a totals row
    "day | DSA\nMon | --", // not the "-" for no time
  ]) {
    assert.equal(schedule(bad, MONDAY), null, JSON.stringify(bad));
  }
});

test("blank lines inside a schedule are skipped", () => {
  assert.deepEqual(textsOf(schedule("day | A\n\nMon | 1\n  \nTue | 2", MONDAY), "nb-name"), ["Mon", "Tue"]);
});

// ---- phases ----

// 10 + 10 + 10 days: Jan 1-10, 11-20, 21-30
const THREE = "P1 First | 2026-01-01 | 2026-01-10 | warm up\nP2 Second | 2026-01-11 | 2026-01-20\nP3 Third | 2026-01-21 | 2026-01-30 | finish";

test("each phase is a segment placed by its share of the whole span", () => {
  const html = phases(THREE, "2026-01-15");
  assert.deepEqual(attrsOf(html, "nb-seg", "data-left"), ["0", "33.33", "66.67"]);
  assert.deepEqual(attrsOf(html, "nb-seg", "data-width"), ["33.33", "33.33", "33.33"]);
});

test("phases before, on and after today are past, now and future", () => {
  const html = phases(THREE, "2026-01-15");
  assert.deepEqual(textsOf(html, "nb-seg"), ["P1", "▶ P2", "P3"]);
  assert.match(html, /<span class="nb-seg nb-past nb-pos"[^>]*>P1</);
  assert.match(html, /<span class="nb-seg nb-now nb-pos"[^>]*>▶ P2</);
  assert.match(html, /<span class="nb-seg nb-future nb-pos"[^>]*>P3</);
  const glyphs = [...html.matchAll(/<li class="nb-phase nb-(\w+)"><span class="nb-phase-head"><span class="nb-glyph" aria-hidden="true">(.)<\/span>/g)];
  assert.deepEqual(glyphs.map((m) => [m[1], m[2]]), [["past", "✓"], ["now", "▶"], ["future", "○"]]);
});

test("a phase's first and last days both count as now", () => {
  assert.match(phases(THREE, "2026-01-11"), /nb-now nb-pos"[^>]*>▶ P2</);
  assert.match(phases(THREE, "2026-01-20"), /nb-now nb-pos"[^>]*>▶ P2</);
  assert.match(phases(THREE, "2026-01-21"), /nb-now nb-pos"[^>]*>▶ P3</);
});

test("the list gives dates, length in weeks, and which week the current phase is in", () => {
  const html = phases("P1 Long | 2026-11-09 | 2027-01-03\nP2 Next | 2027-01-04 | 2027-01-10", MONDAY);
  assert.deepEqual(textsOf(html, "nb-phase-when"), [
    "Nov 9 – Jan 3 · 8 wk · week 2 of 8",
    "Jan 4 – Jan 10 · 1 wk",
  ]);
});

test("a phase of exactly a week and a day is two weeks", () => {
  assert.match(textsOf(phases("P0 | 2026-11-09 | 2026-11-16", "2026-01-01"), "nb-phase-when")[0], /· 2 wk$/);
});

test("a part week rounds the length up", () => {
  assert.deepEqual(textsOf(phases("P1 | 2026-11-09 | 2026-11-17", MONDAY), "nb-phase-when"), ["Nov 9 – Nov 17 · 2 wk · week 2 of 2"]);
});

test("a one-week phase doesn't say which week of itself it's in", () => {
  assert.deepEqual(textsOf(phases("W2 | 2026-11-16 | 2026-11-22", MONDAY), "nb-phase-when"), ["Nov 16 – Nov 22 · 1 wk"]);
});

test("a note may follow the end date after a colon or a dash", () => {
  assert.deepEqual(textsOf(phases("P1 | 2026-01-01 | 2026-01-10: warm up", MONDAY), "nb-phase-note"), ["warm up"]);
  assert.deepEqual(textsOf(phases("P1 2026-01-01 2026-01-10 - warm up", MONDAY), "nb-phase-note"), ["warm up"]);
});

test("notes follow the dates; a phase without one has none", () => {
  assert.deepEqual(textsOf(phases(THREE, MONDAY), "nb-phase-note"), ["warm up", "finish"]);
});

test("phases can be written with spaces instead of pipes", () => {
  const html = phases("P1 Setup weekend   2026-11-07  2026-11-08  resume v1, trackers", MONDAY);
  assert.deepEqual(textsOf(html, "nb-name"), ["P1 Setup weekend"]);
  assert.deepEqual(textsOf(html, "nb-phase-note"), ["resume v1, trackers"]);
});

test("the today line sits where today falls, labelled, only inside the span", () => {
  assert.deepEqual(attrsOf(phases(THREE, "2026-01-16"), "nb-today", "data-left"), ["50"]);
  assert.ok(phases(THREE, "2026-01-16").includes('<span class="nb-today-label">today</span>'));
  assert.ok(!phases(THREE, "2025-12-31").includes("nb-today"));
  assert.ok(!phases(THREE, "2026-01-31").includes("nb-today"));
});

test("the today line sits at the very start or end on the span's first or last day", () => {
  const span = "P1 | 2026-01-01 | 2026-01-10";
  assert.deepEqual(attrsOf(phases(span, "2026-01-01"), "nb-today", "data-left"), ["0"]);
  assert.deepEqual(attrsOf(phases(span, "2026-01-10"), "nb-today", "data-left"), ["90"]);
});

test("a span starting late in a month still ticks the next month first", () => {
  assert.deepEqual(textsOf(phases("P1 | 2026-01-31 | 2026-03-31", "2026-02-01"), "nb-tick"), ["Feb", "Mar"]);
});

test("a span ending on the 1st ticks that month too", () => {
  assert.deepEqual(textsOf(phases("P | 2026-01-15 | 2026-03-01", MONDAY), "nb-tick"), ["Feb", "Mar"]);
});

test("a span of more than 20 years is refused as a typo", () => {
  assert.equal(phases("P | 0100-01-01 | 9999-12-31", MONDAY), null);
  assert.equal(phases("P1 | 2026-01-01 | 2026-01-31\nP2 | 2066-01-01 | 2066-01-31", MONDAY), null);
  assert.notEqual(phases("P | 2026-01-01 | 2045-12-31", MONDAY), null);
});

test("a month tick marks the first of each month after the start", () => {
  const html = phases("P1 | 2026-01-01 | 2026-03-31", "2026-02-01");
  assert.deepEqual(textsOf(html, "nb-tick"), ["Feb", "Mar"]);
  assert.deepEqual(attrsOf(html, "nb-tick", "data-left"), ["34.44", "65.56"]); // day 31 and 59 of 90
});

test("before every phase all are future and nothing is marked current", () => {
  const html = phases(THREE, "2025-06-01");
  assert.ok(!html.includes("nb-past") && !html.includes("nb-now"));
  assert.ok(!html.includes("week "));
});

test("without a valid today every phase and step is still to come, whatever its date", () => {
  const html = phases("P0 | 1960-01-01 | 1960-01-31\nP1 | 1975-01-01 | 1975-01-31", "not a date");
  assert.ok(!html.includes("nb-past") && !html.includes("nb-now") && !html.includes("nb-today"));
  assert.deepEqual(textsOf(targets("W1 | 1960-01-04 | 8", "not a date"), "nb-where"), ["○ plan not started"]);
});

test("phase names and notes are escaped", () => {
  const html = phases("<i>P1</i> | 2026-01-01 | 2026-01-02 | a & b", MONDAY);
  assert.ok(!html.includes("<i>"));
  assert.ok(html.includes("&lt;i&gt;P1&lt;/i&gt;"));
  assert.ok(html.includes("a &amp; b"));
});

test("phases that don't fit the format are refused", () => {
  for (const bad of [
    "",
    "P1 | 2026-01-01", // one date
    "| 2026-01-01 | 2026-01-05", // no name
    "P1 | 2026-01-05 | 2026-01-01", // ends before it starts
    "P1 | 2026-01-05 | 2026-01-04", // ends the day before it starts
    "P1 | 2026-02-30 | 2026-03-01", // no such day
    "P1 | 2026-01-01 | 2026-01-05\nwords only", // one bad line spoils the block
  ]) {
    assert.equal(phases(bad, MONDAY), null, JSON.stringify(bad));
  }
});

test("a one-day phase is allowed and counts as one week", () => {
  const html = phases("P0 | 2026-11-16 | 2026-11-16", MONDAY);
  assert.deepEqual(attrsOf(html, "nb-seg", "data-width"), ["100"]);
  assert.deepEqual(textsOf(html, "nb-phase-when"), ["Nov 16 – Nov 16 · 1 wk"]);
});

// ---- targets ----

const PLAN = "unit: problems\nW1 | 2026-11-09 | 8 | Arrays\nW2 | 2026-11-16 | 20 | Two Pointers\nW3 | 2026-11-23 | 20 | rest\nW4 | 2026-11-30 | 30";

test("the big number is the total planned by the end of the current step", () => {
  const html = targets(PLAN, MONDAY);
  assert.deepEqual(textsOf(html, "nb-big"), ["20"]);
  assert.deepEqual(textsOf(html, "nb-of"), ["/ 30 problems"]);
  assert.deepEqual(textsOf(html, "nb-where"), ["▶ planned by the end of W2"]);
});

test("spaces around the unit are trimmed", () => {
  assert.deepEqual(textsOf(targets("unit:  km  \nW1 | 2026-11-09 | 8", MONDAY), "nb-of"), ["/ 8 km"]);
});

test("without a unit line the goal is just a number", () => {
  assert.deepEqual(textsOf(targets("W1 | 2026-11-09 | 8", MONDAY), "nb-of"), ["/ 8"]);
});

test("before the first step nothing is planned yet", () => {
  const html = targets(PLAN, "2026-11-08");
  assert.deepEqual(textsOf(html, "nb-big"), ["0"]);
  assert.deepEqual(textsOf(html, "nb-where"), ["○ plan not started"]);
  assert.ok(!html.includes("nb-past") && !html.includes("nb-now"));
});

test("after the last step starts, the whole goal is planned", () => {
  assert.deepEqual(textsOf(targets(PLAN, "2027-06-01"), "nb-big"), ["30"]);
});

test("the bar has one segment per step that adds something, sized by what it adds", () => {
  const html = targets(PLAN, MONDAY);
  assert.deepEqual(attrsOf(html, "nb-seg", "data-left"), ["0", "26.67", "66.67"]);
  assert.deepEqual(attrsOf(html, "nb-seg", "data-width"), ["26.67", "40", "33.33"]);
  assert.deepEqual(attrsOf(html, "nb-seg", "title"), ["W1: +8, 8 total", "W2: +12, 20 total", "W4: +10, 30 total"]);
  assert.match(html, /nb-seg nb-past nb-pos" data-left="0"/);
  assert.match(html, /nb-seg nb-now nb-pos" data-left="26.67"/);
  assert.match(html, /nb-seg nb-future nb-pos" data-left="66.67"/);
});

test("the week-by-week list shows each step's date, amount added, running total and note", () => {
  const html = targets(PLAN, MONDAY);
  assert.ok(html.includes("<summary>week by week (4)</summary>"));
  assert.deepEqual(textsOf(html, "nb-step-date"), ["Nov 9", "Nov 16", "Nov 23", "Nov 30"]);
  assert.deepEqual(textsOf(html, "nb-step-add"), ["+8", "+12", "+0", "+10"]);
  assert.deepEqual(textsOf(html, "nb-step-total"), ["8", "20", "20", "30"]);
  assert.deepEqual(textsOf(html, "nb-step-note"), ["Arrays", "Two Pointers", "rest", ""]);
  const states = [...html.matchAll(/<li class="nb-step nb-(\w+)"><span class="nb-glyph" aria-hidden="true">(.)</g)];
  assert.deepEqual(states.map((m) => [m[1], m[2]]), [["past", "✓"], ["now", "▶"], ["future", "○"], ["future", "○"]]);
});

test("a note containing pipes keeps them", () => {
  assert.deepEqual(textsOf(targets("W1 | 2026-11-09 | 8 | a | b", MONDAY), "nb-step-note"), ["a | b"]);
});

test("targets can be written with spaces instead of pipes", () => {
  const html = targets("Unit: km\nW1   2026-11-09   8   easy", MONDAY);
  assert.deepEqual(textsOf(html, "nb-of"), ["/ 8 km"]);
  assert.deepEqual(textsOf(html, "nb-step-note"), ["easy"]);
});

test("a space-separated note keeps its own wide gaps, not pipes", () => {
  assert.deepEqual(textsOf(targets("W1   2026-11-09   8   easy  run", MONDAY), "nb-step-note"), ["easy  run"]);
});

test("target names, units and notes are escaped", () => {
  const html = targets("unit: <u>\n<b>W1</b> | 2026-11-09 | 8 | a & b", MONDAY);
  assert.ok(!html.includes("<u>") && !html.includes("<b>"));
  assert.ok(html.includes("/ 8 &lt;u&gt;"));
  assert.ok(html.includes("a &amp; b"));
});

test("targets that don't fit the format are refused", () => {
  for (const bad of [
    "",
    "unit: problems", // a unit but no steps
    "W1 | soon | 8", // not a date
    "W1 | 2026-11-09 | eight", // not a number
    "W1 | 2026-11-09", // no total
    "W1 | 2026-11-09 | 8\nW2 | 2026-11-16 | 5", // the running total went down
    "W1 | 2026-11-30 | 8\nW2 | 2026-11-09 | 20", // a step dated before the one above
    "W1 | 2026-11-09 | 8\nW2 | 2026-11-09 | 20", // two steps on one day
  ]) {
    assert.equal(targets(bad, MONDAY), null, JSON.stringify(bad));
  }
});

// ---- callout styles ----

test("calloutStyle gives a known kind its tone and symbol, ignoring case", () => {
  assert.deepEqual(calloutStyle("ALARM"), { tone: "flame", glyph: "⚠" });
  assert.deepEqual(calloutStyle("Tip"), { tone: "moss", glyph: "✦" });
});

test("calloutStyle gives any other kind the plain ink style", () => {
  assert.deepEqual(calloutStyle("reminder"), { tone: "ink", glyph: "◆" });
  assert.deepEqual(calloutStyle("constructor"), { tone: "ink", glyph: "◆" }); // not an Object property
});
