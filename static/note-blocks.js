// Data blocks for idea notes: a fenced code block tagged `schedule`,
// `phases` or `targets` is drawn as a picture of its data instead of as
// code, in the stats page's visual language (moss heat levels, bars, a
// today marker). The text inside stays plain and readable in the CLI.
//
// Each renderer takes the block's text and today's date ("YYYY-MM-DD") and
// returns HTML, or null when the text doesn't fit the format -- the block
// then shows as ordinary code, so a typo never hides what was written.
// Columns are separated by "|" or by two or more spaces.
//
// Bar positions travel as data-left/data-width (percent) because the
// sanitizer strips inline styles; markdown.js applies them afterwards.

(() => {
const ISO_DATE = /\b(\d{4})-(\d{2})-(\d{2})\b/g;
const MS_PER_DAY = 86400000;
const DAYS_PER_WEEK = 7;
const HEAT_LEVELS = 4;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function splitCells(line) {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return trimmed.split(/\s{2,}|\t+/);
  return trimmed.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

function contentLines(text) {
  return text.split("\n").filter((line) => line.trim() !== "");
}

// Days since 1970 for a valid "YYYY-MM-DD", else null -- whole days, so
// time zones never shift a date.
function dayNumber(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const [year, month, day] = match.slice(1).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day); // unlike Date.UTC, keeps years 0-99 as typed
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.getTime() / MS_PER_DAY;
}

function shortDate(day) {
  const date = new Date(day * MS_PER_DAY);
  return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
}

const roundToHundredths = (value) => Math.round(value * 100) / 100;

function formatNumber(value) {
  return String(Number.isInteger(value) ? value : roundToHundredths(value));
}

function percent(fraction) {
  return roundToHundredths(fraction * 100);
}

const sum = (values) => values.reduce((total, value) => total + value, 0);

// Both the first and the last day count.
const daysInclusive = (start, end) => end - start + 1;

// Where a bar or marker sits, in percent; markdown.js turns these into styles.
function positionAttrs(left, width) {
  return `data-left="${left}"` + (width === undefined ? "" : ` data-width="${width}"`);
}

// "Sat (first 1.5h = mock)" -> name "Sat", aside "(first 1.5h = mock)"
function splitAside(label) {
  const match = /^(.*?)\s*(\(.*\))$/.exec(label);
  return match && match[1] ? { name: match[1], aside: match[2] } : { name: label, aside: "" };
}

function labelHtml(label, nameClass) {
  const { name, aside } = splitAside(label);
  const asideHtml = aside ? `<span class="nb-aside">${escapeHtml(aside)}</span>` : "";
  return `<span class="${nameClass}">${escapeHtml(name)}</span>${asideHtml}`;
}

// done / happening now / still to come
const STATE_GLYPHS = { past: "✓", now: "▶", future: "○" };

function stateGlyph(state) {
  return `<span class="nb-glyph" aria-hidden="true">${STATE_GLYPHS[state]}</span>`;
}

// ---- schedule: hours per day and activity, as a heat grid ----
//
//   day   DSA  Skill  Apply
//   Mon   2    1      -
//   Wed   2    -      1.5
//
// "-" or an empty cell is no time. A row named "Total" is ignored: totals
// are always worked out from the rows, so they can't disagree with them.

const EMPTY_CELL = /^-?$/;
const NUMBER = /^\d+(\.\d+)?$/;
const TOTAL_LABEL = /^total(?:\s*\(.*\))?$/i; // "Total", "Total (week)"

function parseSchedule(text) {
  const [header, ...body] = contentLines(text).map(splitCells);
  if (!header || header.length < 2) return null;
  const columns = header.slice(1);
  const rows = [];
  for (const cells of body) {
    if (TOTAL_LABEL.test(cells[0])) continue;
    const values = cells.slice(1);
    if (values.length > columns.length) return null;
    if (!values.every((value) => EMPTY_CELL.test(value) || NUMBER.test(value))) return null;
    const hours = columns.map((_, index) => (NUMBER.test(values[index] ?? "") ? Number(values[index]) : 0));
    rows.push({ label: cells[0], hours });
  }
  return rows.length ? { corner: header[0], columns, rows } : null;
}

function heatLevel(value, max) {
  return value > 0 ? Math.ceil((value / max) * HEAT_LEVELS) : 0;
}

// "Mon", "monday", "Mon (DSA slot)" -> 1; "Month", "Weekend" -> null
const WEEKDAY_NAMES = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const WEEKDAY_ABBREVIATION_LENGTH = 3;

function weekdayOf(label) {
  const word = label.trim().split(/[\s(]/)[0].toLowerCase();
  if (word.length < WEEKDAY_ABBREVIATION_LENGTH) return null;
  const index = WEEKDAY_NAMES.findIndex((name) => name.startsWith(word));
  return index === -1 ? null : index;
}

function weekdayOfDay(day) {
  return day === null ? null : new Date(day * MS_PER_DAY).getUTCDay();
}

function scheduleHeadHtml(corner, columns) {
  return (
    `<div class="nb-sched-row nb-sched-head"><span class="nb-sched-label">${escapeHtml(corner)}</span>` +
    columns.map((name) => `<span class="nb-sched-col">${escapeHtml(name)}</span>`).join("") +
    `<span class="nb-sched-sum" title="total">Σ</span></div>`
  );
}

function heatCellHtml(value, column, max) {
  const tip = `${column}: ${value > 0 ? `${formatNumber(value)}h` : "none"}`;
  const shown = value > 0 ? formatNumber(value) : "";
  return `<span class="nb-heat" data-level="${heatLevel(value, max)}" title="${escapeHtml(tip)}">${shown}</span>`;
}

function scheduleRowHtml({ label, hours }, { columns, max, isToday }) {
  const todayMark = isToday ? stateGlyph("now") : "";
  return (
    `<div class="nb-sched-row${isToday ? " nb-now" : ""}"><span class="nb-sched-label">${todayMark}${labelHtml(label, "nb-name")}</span>` +
    hours.map((value, index) => heatCellHtml(value, columns[index], max)).join("") +
    `<span class="nb-sched-sum">${formatNumber(sum(hours))}h</span></div>`
  );
}

function scheduleFootHtml(columnTotals) {
  return (
    `<div class="nb-sched-row nb-sched-foot"><span class="nb-sched-label">Σ total</span>` +
    columnTotals.map((value) => `<span class="nb-sched-col">${formatNumber(value)}h</span>`).join("") +
    `<span class="nb-sched-sum">${formatNumber(sum(columnTotals))}h</span></div>`
  );
}

function renderSchedule(text, todayIso) {
  const schedule = parseSchedule(text);
  if (!schedule) return null;
  const { corner, columns, rows } = schedule;
  const max = Math.max(...rows.flatMap((row) => row.hours));
  const columnTotals = columns.map((_, index) => sum(rows.map((row) => row.hours[index])));
  const todayWeekday = weekdayOfDay(dayNumber(todayIso));
  const body = rows.map((row) =>
    scheduleRowHtml(row, { columns, max, isToday: todayWeekday !== null && weekdayOf(row.label) === todayWeekday })
  );
  return (
    `<div class="nb-block nb-schedule" data-cols="${columns.length}">` +
    `${scheduleHeadHtml(corner, columns)}${body.join("")}${scheduleFootHtml(columnTotals)}</div>\n`
  );
}

// ---- phases: date ranges on a timeline ----
//
//   P1 Foundations   2026-11-09  2027-01-03  NeetCode 150 first 80
//
// A name, a start and an end date (both days included), then an optional
// note.

// A plan spanning more than this is a typo (a wrong year); drawing it
// would mean thousands of month ticks.
const MAX_PHASES_SPAN_DAYS = 20 * 366;

function parsePhases(text) {
  const phases = [];
  for (const line of contentLines(text)) {
    const dates = [...line.matchAll(ISO_DATE)];
    if (dates.length < 2) return null;
    const start = dayNumber(dates[0][0]);
    const end = dayNumber(dates[1][0]);
    if (start === null || end === null || end < start) return null;
    const name = line.slice(0, dates[0].index).replace(/[|\s]+$/, "").trim();
    const note = line.slice(dates[1].index + dates[1][0].length).replace(/^[|\s:-]+/, "").trim();
    if (!name) return null;
    phases.push({ name, start, end, note });
  }
  if (!phases.length) return null;
  const first = Math.min(...phases.map((phase) => phase.start));
  const last = Math.max(...phases.map((phase) => phase.end));
  return daysInclusive(first, last) > MAX_PHASES_SPAN_DAYS ? null : phases;
}

// Without a valid today, nothing has started yet.
function phaseState(phase, today) {
  if (today === null || today < phase.start) return "future";
  if (today > phase.end) return "past";
  return "now";
}

function monthTicks(first, last) {
  const ticks = [];
  const date = new Date(first * MS_PER_DAY);
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() + 1);
  while (date.getTime() / MS_PER_DAY <= last) {
    ticks.push({ day: date.getTime() / MS_PER_DAY, label: MONTHS[date.getUTCMonth()] });
    date.setUTCMonth(date.getUTCMonth() + 1);
  }
  return ticks;
}

// The span every phase is drawn against: `at(day)` is how far along it a
// day falls, `share(days)` how much of it a number of days takes up.
function timeline(phases) {
  const first = Math.min(...phases.map((phase) => phase.start));
  const last = Math.max(...phases.map((phase) => phase.end));
  const span = daysInclusive(first, last);
  return { first, last, at: (day) => percent((day - first) / span), share: (days) => percent(days / span) };
}

function phaseSegmentHtml(phase, state, { at, share }) {
  const short = `${state === "now" ? `${STATE_GLYPHS.now} ` : ""}${phase.name.split(/\s+/)[0]}`;
  const title = `${phase.name}: ${shortDate(phase.start)} – ${shortDate(phase.end)}`;
  return (
    `<span class="nb-seg nb-${state} nb-pos" ${positionAttrs(at(phase.start), share(daysInclusive(phase.start, phase.end)))} ` +
    `title="${escapeHtml(title)}">${escapeHtml(short)}</span>`
  );
}

// "Nov 9 – Jan 3 · 8 wk", plus "· week 2 of 8" while it's happening
function phaseWhen(phase, state, today) {
  const weeks = Math.ceil(daysInclusive(phase.start, phase.end) / DAYS_PER_WEEK);
  const when = `${shortDate(phase.start)} – ${shortDate(phase.end)} · ${weeks} wk`;
  if (state !== "now" || weeks === 1) return when;
  return `${when} · week ${Math.floor((today - phase.start) / DAYS_PER_WEEK) + 1} of ${weeks}`;
}

function phaseItemHtml(phase, state, today) {
  const note = phase.note ? `<span class="nb-phase-note">${escapeHtml(phase.note)}</span>` : "";
  return (
    `<li class="nb-phase nb-${state}"><span class="nb-phase-head">${stateGlyph(state)}${labelHtml(phase.name, "nb-name")}` +
    `<span class="nb-phase-when">${phaseWhen(phase, state, today)}</span></span>${note}</li>`
  );
}

function renderPhases(text, todayIso) {
  const phases = parsePhases(text);
  if (!phases) return null;
  const today = dayNumber(todayIso);
  const span = timeline(phases);
  const states = phases.map((phase) => phaseState(phase, today));

  const segments = phases.map((phase, index) => phaseSegmentHtml(phase, states[index], span));
  const ticks = monthTicks(span.first, span.last).map(
    ({ day, label }) => `<span class="nb-tick nb-pos" ${positionAttrs(span.at(day))}>${label}</span>`
  );
  const todayMark =
    today !== null && today >= span.first && today <= span.last
      ? `<span class="nb-today nb-pos" ${positionAttrs(span.at(today))}><span class="nb-today-label">today</span></span>`
      : "";
  const list = phases.map((phase, index) => phaseItemHtml(phase, states[index], today));

  return (
    `<div class="nb-block nb-phases"><div class="nb-strip">${segments.join("")}${todayMark}</div>` +
    `<div class="nb-ticks">${ticks.join("")}</div><ol class="nb-phase-list">${list.join("")}</ol></div>\n`
  );
}

// ---- targets: a cumulative plan, week by week ----
//
//   unit: problems
//   W1   2026-11-09   8    Arrays & Hashing x8
//   W2   2026-11-16   20   Two Pointers x5, Stack x6
//
// A name, the day it starts, the running total planned by its end, and an
// optional note. Steps go forward in time and the total never shrinks.
// An optional first line "unit: ..." names what's counted.

const UNIT_LINE = /^\s*unit\s*:\s*(.+)$/i;

// What follows the fixed columns, as typed: cells are rejoined with the
// separator they were split on.
function noteText(line, rest) {
  return rest.join(line.includes("|") ? " | " : "  ");
}

function parseTargets(text) {
  const lines = contentLines(text);
  const unitMatch = lines.length ? UNIT_LINE.exec(lines[0]) : null;
  const unit = unitMatch ? unitMatch[1].trim() : "";
  const steps = [];
  for (const line of unitMatch ? lines.slice(1) : lines) {
    const [name, date, totalText, ...rest] = splitCells(line);
    const start = dayNumber(date ?? "");
    if (!name || start === null || !NUMBER.test(totalText ?? "")) return null;
    const total = Number(totalText);
    const last = steps[steps.length - 1];
    if (last && (start <= last.start || total < last.total)) return null;
    steps.push({ name, start, total, added: total - (last ? last.total : 0), note: noteText(line, rest) });
  }
  return steps.length ? { unit, steps } : null;
}

// The last step that has started; -1 before the first (or without a today).
function currentStepIndex(steps, today) {
  return today === null ? -1 : steps.findLastIndex((step) => step.start <= today);
}

function stepState(index, currentIndex) {
  if (index < currentIndex) return "past";
  return index === currentIndex ? "now" : "future";
}

// One bar segment per step that adds something, laid end to end.
function targetSegmentsHtml(steps, states, goal) {
  let before = 0;
  const segments = [];
  steps.forEach((step, index) => {
    if (step.added <= 0) return;
    const title = `${step.name}: +${formatNumber(step.added)}, ${formatNumber(step.total)} total`;
    segments.push(
      `<span class="nb-seg nb-${states[index]} nb-pos" ${positionAttrs(percent(before / goal), percent(step.added / goal))} ` +
        `title="${escapeHtml(title)}"></span>`
    );
    before += step.added;
  });
  return segments.join("");
}

function targetStepHtml(step, state) {
  return (
    `<li class="nb-step nb-${state}">${stateGlyph(state)}<span class="nb-name">${escapeHtml(step.name)}</span>` +
    `<span class="nb-step-date">${shortDate(step.start)}</span>` +
    `<span class="nb-step-add">+${formatNumber(step.added)}</span>` +
    `<span class="nb-step-total">${formatNumber(step.total)}</span>` +
    `<span class="nb-step-note">${escapeHtml(step.note)}</span></li>`
  );
}

function targetHeadHtml(plan, currentIndex) {
  const { unit, steps } = plan;
  const goal = steps[steps.length - 1].total;
  const current = steps[currentIndex];
  const where = current
    ? `${STATE_GLYPHS.now} planned by the end of ${escapeHtml(current.name)}`
    : `${STATE_GLYPHS.future} plan not started`;
  return (
    `<div class="nb-target-head"><span class="nb-big">${formatNumber(current ? current.total : 0)}</span>` +
    `<span class="nb-of">/ ${formatNumber(goal)}${unit ? ` ${escapeHtml(unit)}` : ""}</span>` +
    `<span class="nb-where">${where}</span></div>`
  );
}

function renderTargets(text, todayIso) {
  const plan = parseTargets(text);
  if (!plan) return null;
  const { steps } = plan;
  const currentIndex = currentStepIndex(steps, dayNumber(todayIso));
  const states = steps.map((_, index) => stepState(index, currentIndex));
  const goal = steps[steps.length - 1].total;
  return (
    `<div class="nb-block nb-targets">${targetHeadHtml(plan, currentIndex)}` +
    `<div class="nb-strip nb-bar">${targetSegmentsHtml(steps, states, goal)}</div>` +
    `<details class="nb-steps"><summary>week by week (${steps.length})</summary>` +
    `<ol class="nb-step-list">${steps.map((step, index) => targetStepHtml(step, states[index])).join("")}</ol></details></div>\n`
  );
}

// ---- callouts: "> [!ALARM]" ----

const CALLOUT_STYLES = {
  alarm: { tone: "flame", glyph: "⚠" },
  warning: { tone: "flame", glyph: "⚠" },
  caution: { tone: "flame", glyph: "⚠" },
  important: { tone: "flame", glyph: "!" },
  note: { tone: "cobalt", glyph: "ℹ" },
  info: { tone: "cobalt", glyph: "ℹ" },
  tip: { tone: "moss", glyph: "✦" },
  goal: { tone: "moss", glyph: "⚑" },
  win: { tone: "moss", glyph: "★" },
};
const OTHER_CALLOUT = { tone: "ink", glyph: "◆" };

function calloutStyle(kind) {
  const key = kind.toLowerCase();
  return Object.hasOwn(CALLOUT_STYLES, key) ? CALLOUT_STYLES[key] : OTHER_CALLOUT;
}

const api = {
  renderers: { schedule: renderSchedule, phases: renderPhases, targets: renderTargets },
  calloutStyle,
  dayNumber,
};
if (typeof module !== "undefined") module.exports = api;
else globalThis.IdeaNoteBlocks = api;
})();
