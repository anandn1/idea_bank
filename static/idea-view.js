// Full-page idea view (static/idea.html?id=N): everything about one idea --
// status, fields, linked goals with their history, notes, and an activity
// timeline -- from GET /api/ideas/<id>/overview, the same data as
// `idea show <id> --full --json`. Every edit saves straight away (there's
// no "done" step), then the overview is re-fetched so progress and the
// timeline stay current.
//
// Opened from the board modal's "full view" button. Deliberately separate
// from app.js: no board, no card selection, its own save model.

const STATUSES = ["inbox", "active", "queued", "horizon", "frontier", "archive"];
const XP_SEGMENTS = 24;
const MINI_HEATMAP_WEEKS = 12;
const NOTES_SAVE_DELAY_MS = 1200;
const MS_PER_DAY = 24 * 60 * 60 * 1000;
const TAB_TITLE_MAX_CHARS = 40;
const TIMELINE_GLYPHS = {
  created: "●",
  status: "◆",
  goal_created: "+",
  goal_stopped: "■",
  goal_done: "✓",
};

const ideaId = Number(new URLSearchParams(window.location.search).get("id"));
let overview = null;

const $ = (id) => document.getElementById(id);
const viewEl = $("idea-view");
const titleEl = $("view-title");
const saveStateEl = $("view-save-state");
const fieldSheetEl = $("field-sheet");
const notesEditorEl = $("notes-editor");

const notesEditor = IdeaMarkdown.createNotesEditor({
  viewEl: $("notes-view"),
  textareaEl: notesEditorEl,
  toggleEl: $("notes-toggle"),
  onRender: renderChapters,
});

// ---- small helpers ----

// Server timestamps are "YYYY-MM-DD HH:MM:SS".
const datePart = (timestamp) => timestamp.slice(0, "YYYY-MM-DD".length);
const toTheMinute = (timestamp) => timestamp.slice(0, "YYYY-MM-DD HH:MM".length);
const clockTime = () => new Date().toTimeString().slice(0, "HH:MM".length);

function daysBetween(fromIso, toIso) {
  return Math.round((parseLocalDate(toIso) - parseLocalDate(fromIso)) / MS_PER_DAY);
}

// Same default as the board: dark unless "light" or "system" was chosen.
function applyStoredTheme() {
  const stored = readStoredTheme();
  if (stored !== "system") document.documentElement.dataset.theme = stored === "light" ? "light" : "dark";
}

// ---- loading and saving ----

function showNotice(message) {
  viewEl.hidden = true;
  const notice = $("view-notice");
  notice.textContent = message;
  notice.hidden = false;
}

async function fetchOverview() {
  let res;
  try {
    res = await fetch(`/api/ideas/${ideaId}/overview`);
  } catch {
    showNotice("couldn't reach the server -- is it running?");
    return null;
  }
  if (res.status === 404) {
    showNotice("this idea no longer exists -- it may have been deleted");
    return null;
  }
  if (!res.ok) {
    showNotice("couldn't load this idea -- is the server running?");
    return null;
  }
  return res.json();
}

async function load() {
  if (!ideaId) {
    showNotice("no idea id in the address -- open this page from the board");
    return;
  }
  overview = await fetchOverview();
  if (!overview) return;
  renderAll();
  notesEditor.setNotes(overview.idea.notes || "");
  renderChapters($("notes-view"));
  viewEl.hidden = false;
  fitTitle(); // needs the page visible to measure
}

async function refresh() {
  const latest = await fetchOverview();
  if (!latest) return;
  overview = latest;
  renderAll();
}

function setSaveState(text, isError) {
  saveStateEl.textContent = text;
  saveStateEl.classList.toggle("error", Boolean(isError));
}

function patchJson(url, body, options = {}) {
  return fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    ...options,
  });
}

async function saveIdea(changes) {
  setSaveState("saving…");
  try {
    const res = await patchJson(`/api/ideas/${ideaId}`, changes);
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    setSaveState(`saved ${clockTime()}`);
    await refresh();
  } catch (error) {
    setSaveState(`not saved: ${error.message}`, true);
  }
}

// ---- hero: title, status, progress ----

function fitTitle() {
  titleEl.style.height = "auto";
  titleEl.style.height = `${titleEl.scrollHeight}px`;
}

function renderHero() {
  const { idea, progress, goals } = overview;
  document.title =
    idea.text.length <= TAB_TITLE_MAX_CHARS
      ? idea.text
      : idea.text.slice(0, TAB_TITLE_MAX_CHARS - "...".length) + "...";
  $("view-cmd").textContent = `idea show ${idea.id} --full`;
  $("view-eyebrow").textContent = `idea #${idea.id} · day ${daysBetween(datePart(idea.created_at), overview.today) + 1}`;

  if (document.activeElement !== titleEl) {
    titleEl.value = idea.text;
    fitTitle();
  }

  renderStatusPills(idea.status);
  $("view-meta").textContent =
    `created ${toTheMinute(idea.created_at)} · updated ${relativeTime(idea.updated_at)}`;
  renderXp(progress);
  renderTiles(goals, progress);
}

function renderStatusPills(current) {
  const pills = $("view-status-pills");
  pills.replaceChildren();
  for (const status of STATUSES) {
    const pill = el("button", "target-pill" + (status === current ? " selected" : ""), status);
    pill.type = "button";
    pill.dataset.status = status;
    pill.setAttribute("aria-pressed", String(status === current));
    pill.addEventListener("click", () => {
      if (status !== overview.idea.status) saveIdea({ status });
    });
    pills.appendChild(pill);
  }
}

function renderXp(progress) {
  const bar = $("view-xp-bar");
  bar.replaceChildren();
  const filled = Math.round((progress.rate || 0) * XP_SEGMENTS);
  for (let i = 0; i < XP_SEGMENTS; i++) bar.appendChild(el("span", "xp-seg" + (i < filled ? " on" : "")));
  const label = $("view-xp-label");
  if (progress.rate === null) {
    bar.setAttribute("aria-label", "no progress yet");
    label.textContent = "no goal history yet -- link goals to this idea from the goals tab";
    return;
  }
  bar.setAttribute("aria-label", `${formatPercent(progress.rate)} of goal-days done`);
  label.replaceChildren(
    el("strong", null, formatPercent(progress.rate)),
    document.createTextNode(` of goal-days done · ${progress.done}/${progress.due} · ${progress.checkoffs} check-offs`)
  );
}

function buildTile(value, label, accent) {
  const tile = el("div", "view-tile" + (accent ? " accent" : ""));
  tile.append(el("div", "view-tile-value", value), el("div", "view-tile-label", label));
  return tile;
}

function renderTiles(goals, progress) {
  const dueToday = goals.filter((g) => g.due_today);
  const doneToday = dueToday.filter((g) => g.done_today).length;
  const streak = Math.max(0, ...goals.map((g) => g.streak));
  const best = Math.max(0, ...goals.map((g) => g.best_streak));
  $("view-tiles").replaceChildren(
    buildTile(`${doneToday}/${dueToday.length}`, "due today", dueToday.length > 0 && doneToday === dueToday.length),
    buildTile(`${streak}d`, "top streak", streak > 0),
    buildTile(`${best}d`, "best streak"),
    buildTile(String(goals.length), goals.length === 1 ? "goal linked" : "goals linked"),
    buildTile(String(progress.checkoffs), "check-offs")
  );
}

// Idea text is one line (the CLI prints it as a header), so a pasted or
// typed line break becomes a space and Enter -- with or without Shift --
// saves instead of breaking the line.
titleEl.addEventListener("input", () => {
  if (/[\r\n]/.test(titleEl.value)) titleEl.value = titleEl.value.replace(/[\r\n]+/g, " ");
  fitTitle();
});
titleEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    titleEl.blur();
  } else if (e.key === "Escape") {
    titleEl.value = overview.idea.text;
    titleEl.blur();
  }
});
titleEl.addEventListener("blur", () => {
  const text = titleEl.value.trim();
  if (!text) {
    titleEl.value = overview.idea.text;
    fitTitle();
    setSaveState("idea text can't be empty -- kept the old text", true);
    return;
  }
  if (text !== overview.idea.text) saveIdea({ text });
});

// ---- objectives (linked goals) ----

function isFinished(goal) {
  if (goal.weekdays) return goal.archived_at !== null;
  return goal.completed || (goal.target_date !== null && goal.target_date < overview.today);
}

function buildCheck(goal) {
  const check = el("button", "goal-check");
  check.type = "button";
  if (goal.due_today) {
    check.textContent = goal.done_today ? "[x]" : "[ ]";
    check.classList.toggle("done", goal.done_today);
    check.setAttribute("aria-pressed", String(goal.done_today));
    check.setAttribute("aria-label", `${goal.done_today ? "undo" : "check off"} "${goal.text}" for today`);
    check.addEventListener("click", () => toggleGoalToday(goal));
  } else {
    const done = !goal.weekdays && goal.completed;
    check.textContent = done ? "[x]" : " - ";
    check.classList.toggle("done", done);
    check.disabled = true;
    check.title = done ? "done" : "not due today";
  }
  return check;
}

async function toggleGoalToday(goal) {
  setSaveState("saving…");
  let res;
  try {
    res = await patchJson(`/api/goals/${goal.id}`, { completed: !goal.done_today });
  } catch {
    setSaveState("not saved: couldn't reach the server", true);
    return;
  }
  if (!res.ok) {
    setSaveState("not saved: couldn't update that goal", true);
    return;
  }
  setSaveState(`saved ${clockTime()}`);
  await refresh();
}

function heatmapLevel(day) {
  if (!day.due) return "none";
  return day.done ? "4" : "missed";
}

// 12 Monday-aligned week columns, newest on the right.
function buildMiniHeatmap(recent) {
  const lastDay = parseLocalDate(recent[recent.length - 1].date);
  const lastMonday = new Date(lastDay);
  lastMonday.setDate(lastDay.getDate() - mondayFirstWeekday(lastDay));
  const firstMonday = new Date(lastMonday);
  firstMonday.setDate(lastMonday.getDate() - 7 * (MINI_HEATMAP_WEEKS - 1));

  const grid = el("div", "mini-heatmap");
  grid.setAttribute("role", "img");
  const shown = recent.filter((day) => parseLocalDate(day.date) >= firstMonday);
  const doneCount = shown.filter((d) => d.done).length;
  const dueCount = shown.filter((d) => d.due).length;
  grid.setAttribute("aria-label", `last ${MINI_HEATMAP_WEEKS} weeks: ${doneCount} of ${dueCount} due days done`);
  const padding = mondayFirstWeekday(parseLocalDate(shown[0].date));
  for (let i = 0; i < padding; i++) grid.appendChild(el("span", "heatmap-cell blank"));
  for (const day of shown) {
    const cell = el("span", "heatmap-cell");
    cell.dataset.level = heatmapLevel(day);
    if (day.date === overview.today && day.due && !day.done) cell.classList.add("today");
    cell.title = `${day.date}: ${day.due ? (day.done ? "done" : "missed") : "not due"}`;
    grid.appendChild(cell);
  }
  return grid;
}

function buildRateBar(rate) {
  const track = el("div", "rate-bar");
  const fill = el("div", "rate-bar-fill");
  fill.style.width = `${(rate || 0) * 100}%`;
  track.appendChild(fill);
  return track;
}

function oneOffSummary(goal) {
  if (goal.completed) return `done ${goal.last_completed}`;
  if (goal.target_date === null) return "no date set"; // old rows can lack one; never due
  const days = daysBetween(overview.today, goal.target_date);
  if (days < 0) return `missed · was due ${goal.target_date}`;
  if (days === 0) return "due today";
  return `due ${goal.target_date} · in ${days}d`;
}

// Rate bar + numbers, then the streak line.
function buildRecurringProgress(goal) {
  const stats = el("div", "objective-stats");
  stats.append(
    buildRateBar(goal.rate),
    el("span", "objective-rate", formatPercent(goal.rate)),
    el("span", "objective-count", `${goal.done}/${goal.due}`)
  );
  const meta = el("div", "objective-meta");
  meta.append(
    el("span", goal.streak > 0 ? "accent" : null, `streak ${goal.streak}`),
    el("span", null, `best ${goal.best_streak}`),
    el("span", null, `last done ${goal.last_done || "never"}`)
  );
  return [stats, meta];
}

function buildObjective(goal) {
  const row = el("div", "objective" + (isFinished(goal) ? " finished" : ""));
  row.appendChild(buildCheck(goal));

  const body = el("div", "objective-body");
  const head = el("div", "objective-head");
  head.append(el("span", "objective-text", goal.text), el("span", "goal-tag", formatWeekdays(goal.weekdays)));
  if (goal.archived_at) head.appendChild(el("span", "goal-tag", `stopped ${datePart(goal.archived_at)}`));
  body.appendChild(head);
  if (goal.weekdays) body.append(...buildRecurringProgress(goal));
  else body.appendChild(el("div", "objective-meta", oneOffSummary(goal)));
  row.appendChild(body);

  if (goal.weekdays) row.appendChild(buildMiniHeatmap(goal.recent));
  return row;
}

function renderObjectives() {
  const { goals } = overview;
  const container = $("objectives");
  container.replaceChildren();
  const dueToday = goals.filter((g) => g.due_today);
  $("objectives-count").textContent = dueToday.length
    ? `${dueToday.filter((g) => g.done_today).length}/${dueToday.length} today`
    : "";

  if (goals.length === 0) {
    container.appendChild(
      el("p", "panel-empty", "no goals linked yet -- add one on the goals tab and link it to this idea")
    );
    return;
  }
  const current = goals.filter((g) => !isFinished(g));
  const finished = goals.filter(isFinished);
  for (const goal of current) container.appendChild(buildObjective(goal));
  if (finished.length) {
    container.appendChild(el("div", "objective-group-label", "finished"));
    for (const goal of finished) container.appendChild(buildObjective(goal));
  }
}

// ---- fields: a stat sheet, saved whenever a key or value changes ----

// The sheet's fields, or null if two rows share a name -- saving then would
// silently drop one of the two values.
function readFieldSheet() {
  const fields = {};
  for (const row of fieldSheetEl.querySelectorAll(".sheet-row")) {
    const key = row.querySelector(".sheet-key").value.trim();
    if (!key) continue;
    if (Object.hasOwn(fields, key)) return null;
    fields[key] = row.querySelector(".sheet-value").value;
  }
  return fields;
}

function saveFieldSheet() {
  const fields = readFieldSheet();
  if (fields === null) {
    setSaveState("not saved: two fields have the same name", true);
    return;
  }
  if (JSON.stringify(fields) !== JSON.stringify(overview.idea.fields)) saveIdea({ fields });
}

function buildFieldRow(key, value) {
  const row = el("div", "sheet-row");
  const keyInput = el("input", "sheet-key");
  keyInput.value = key;
  keyInput.placeholder = "key";
  keyInput.setAttribute("aria-label", "field name");
  const valueInput = el("input", "sheet-value");
  valueInput.value = value;
  valueInput.placeholder = "value";
  valueInput.setAttribute("aria-label", `value of ${key || "new field"}`);
  const remove = el("button", "sheet-remove", "×");
  remove.type = "button";
  remove.setAttribute("aria-label", `remove field ${key}`);
  remove.addEventListener("click", () => {
    row.remove();
    saveFieldSheet();
  });
  for (const input of [keyInput, valueInput]) input.addEventListener("change", saveFieldSheet);
  row.append(keyInput, valueInput, remove);
  return row;
}

function renderFields() {
  if (fieldSheetEl.contains(document.activeElement)) return; // don't yank a field being typed in
  fieldSheetEl.replaceChildren();
  const entries = Object.entries(overview.idea.fields || {});
  if (entries.length === 0) fieldSheetEl.appendChild(el("p", "panel-empty", "no fields yet"));
  for (const [key, value] of entries) fieldSheetEl.appendChild(buildFieldRow(key, value));
}

$("field-add").addEventListener("click", () => {
  fieldSheetEl.querySelector(".panel-empty")?.remove();
  const row = buildFieldRow("", "");
  fieldSheetEl.appendChild(row);
  row.querySelector(".sheet-key").focus();
});

// ---- chapters: the notes' # and ## headings, numbered in reading order ----

// The heading's own text, without the task count added after it. Raw HTML
// with a heading class has no .md-h-text, so the count is cut from a copy.
function chapterName(heading) {
  const text = heading.querySelector(".md-h-text");
  if (text) return text.textContent.trim();
  const copy = heading.cloneNode(true);
  for (const count of copy.querySelectorAll(".md-h-count")) count.remove();
  return copy.textContent.trim();
}

function renderChapters(notesViewEl) {
  const list = $("chapter-list");
  list.replaceChildren();
  const headings = [...notesViewEl.querySelectorAll(":scope > .md-h1, :scope > .md-h2")];
  $("panel-chapters").hidden = headings.length === 0;
  headings.forEach((heading, index) => {
    heading.id = `chapter-${index + 1}`;
    const item = el("li", heading.classList.contains("md-h1") ? "chapter top" : "chapter");
    const link = el("a", null);
    link.href = `#${heading.id}`;
    link.append(
      el("span", "chapter-num", String(index + 1).padStart(2, "0")),
      el("span", "chapter-name", chapterName(heading))
    );
    item.appendChild(link);
    list.appendChild(item);
  });
}

// ---- timeline ----

const TIMELINE_TEXT = {
  created: () => "idea created",
  status: (e) => `moved ${e.from} → ${e.to}`,
  goal_created: (e) => `goal created: ${e.goal_text}`,
  goal_stopped: (e) => `goal stopped: ${e.goal_text}`,
  goal_done: (e) => `goal done: ${e.goal_text}`,
};

function timelineText(event) {
  const describe = TIMELINE_TEXT[event.kind];
  return describe ? describe(event) : event.kind;
}

function renderTimeline() {
  const list = $("timeline");
  list.replaceChildren();
  for (const event of overview.timeline) {
    const item = el("li", `timeline-item kind-${event.kind}`);
    const glyph = el("span", "timeline-glyph", TIMELINE_GLYPHS[event.kind] || "·");
    glyph.setAttribute("aria-hidden", "true");
    const when = el("time", "timeline-when", datePart(event.at));
    when.dateTime = event.at.replace(" ", "T");
    when.title = event.at;
    item.append(glyph, el("span", "timeline-what", timelineText(event)), when);
    list.appendChild(item);
  }
}

// ---- notes: saved shortly after typing stops, and when the editor loses focus ----

let notesSaveTimer = null;

function saveNotesNow() {
  clearTimeout(notesSaveTimer);
  notesSaveTimer = null;
  const notes = notesEditorEl.value;
  if (notes !== (overview.idea.notes || "")) saveIdea({ notes: notes || null });
}

notesEditorEl.addEventListener("input", () => {
  clearTimeout(notesSaveTimer);
  notesSaveTimer = setTimeout(saveNotesNow, NOTES_SAVE_DELAY_MS);
});
notesEditorEl.addEventListener("blur", saveNotesNow);

// Leaving mid-edit: send whatever's unsaved even as the page unloads.
window.addEventListener("pagehide", () => {
  if (!overview || notesEditorEl.value === (overview.idea.notes || "")) return;
  patchJson(`/api/ideas/${ideaId}`, { notes: notesEditorEl.value || null }, { keepalive: true });
});

// ---- delete ----

$("view-delete").addEventListener("click", async () => {
  if (!window.confirm("Delete this idea? Its goals stay, unlinked. This can't be undone.")) return;
  let res;
  try {
    res = await fetch(`/api/ideas/${ideaId}`, { method: "DELETE" });
  } catch {
    setSaveState("not deleted: couldn't reach the server", true);
    return;
  }
  if (!res.ok) {
    setSaveState("not deleted: the server refused", true);
    return;
  }
  if (window.opener) window.close();
  else window.location.href = "/";
});

function renderAll() {
  renderHero();
  renderObjectives();
  renderFields();
  renderTimeline();
}

applyStoredTheme();
load();
