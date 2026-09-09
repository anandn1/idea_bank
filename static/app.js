const STATUSES = ["inbox", "active", "queued", "horizon", "frontier", "archive"];

let ideas = [];
let flatOrder = [];

let focusId = null; // the keyboard "cursor" position
let selectedIds = new Set(); // ids batch actions apply to (always includes focusId)
let visualAnchorId = null; // non-null while range-select ("visual") mode is active
let editingId = null; // id of the card currently being text-edited, if any

// A goal is its own thing (own text, optionally linked to an idea) --
// completion is always self-reported by the user in the goals panel, never
// derived from an idea's status. See dbutil.py's "goals" section.
let todaysGoals = [];
let streakInfo = { streak: 0, longest: 0, today_complete: false, today_done: 0, today_total: 0, xp: 0 };

const modeIndicator = document.getElementById("mode-indicator");

// ---- theme: dark / light / system, cycled by the top-bar toggle and
// persisted in localStorage. "system" means no explicit override at all --
// style.css's prefers-color-scheme block takes it from there.
const THEME_ORDER = ["dark", "light", "system"];
const THEME_STORAGE_KEY = "idea-bank-theme";
const themeToggle = document.getElementById("theme-toggle");
const themeToggleLabel = document.getElementById("theme-toggle-label");

function applyTheme(theme) {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
  themeToggleLabel.textContent = `theme: ${theme}`;
}

function loadTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    // localStorage unavailable (private browsing, etc.) -- just defaults below
  }
  applyTheme(THEME_ORDER.includes(stored) ? stored : "dark");
}

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.dataset.theme || "system";
  const next = THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length];
  applyTheme(next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // won't persist across reloads, but the click still applies visually
  }
});

loadTheme();

// ---- style: terminal / horizon / notebook, three selectable visual
// identities cycled by their own top-bar toggle and persisted in
// localStorage, mirroring the theme toggle above exactly. See style.css's
// "style" block for what each one actually changes (the --display
// typeface plus a couple of structural flourishes -- never the dark/light
// color tokens, so every style still works in both themes). Pure
// GUI/localStorage state, no CLI equivalent -- same exception as theme. ----
const STYLE_ORDER = ["terminal", "horizon", "notebook"];
const STYLE_STORAGE_KEY = "idea-bank-style";
const styleToggle = document.getElementById("style-toggle");
const styleToggleLabel = document.getElementById("style-toggle-label");

function applyStyle(style) {
  document.documentElement.dataset.style = style;
  styleToggleLabel.textContent = `style: ${style}`;
}

function loadStyle() {
  let stored = null;
  try {
    stored = localStorage.getItem(STYLE_STORAGE_KEY);
  } catch {
    // localStorage unavailable (private browsing, etc.) -- just the default below
  }
  applyStyle(STYLE_ORDER.includes(stored) ? stored : "terminal");
}

styleToggle.addEventListener("click", () => {
  const current = document.documentElement.dataset.style || "terminal";
  const next = STYLE_ORDER[(STYLE_ORDER.indexOf(current) + 1) % STYLE_ORDER.length];
  applyStyle(next);
  try {
    localStorage.setItem(STYLE_STORAGE_KEY, next);
  } catch {
    // won't persist across reloads, but the click still applies visually
  }
});

loadStyle();

function relativeTime(dbTimestamp) {
  const date = new Date(dbTimestamp.replace(" ", "T"));
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));

  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(days / 365);
  return `${years}y ago`;
}

function reduceMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// ---- rendering ----

function buildCard(idea) {
  const card = document.createElement("div");
  const isFocus = idea.id === focusId;
  const isInRange = selectedIds.has(idea.id) && !isFocus;
  card.className = "card" + (isFocus ? " selected" : "") + (isInRange ? " in-range" : "");
  card.dataset.id = idea.id;
  card.dataset.status = idea.status;
  card.tabIndex = -1;

  if (idea.id === editingId) {
    card.appendChild(buildEditField(idea));
    return card;
  }

  const text = document.createElement("div");
  text.className = "card-text";
  text.textContent = idea.text;
  card.appendChild(text);

  const fieldKeys = Object.keys(idea.fields || {});
  if (fieldKeys.length > 0) {
    const fieldsRow = document.createElement("div");
    fieldsRow.className = "card-fields";
    for (const key of fieldKeys) {
      const pill = document.createElement("span");
      pill.className = "field-pill";
      pill.textContent = `${key}: ${idea.fields[key]}`;
      fieldsRow.appendChild(pill);
    }
    card.appendChild(fieldsRow);
  }

  const meta = document.createElement("div");
  meta.className = "card-meta";
  const time = document.createElement("span");
  time.className = "card-time";
  time.textContent = relativeTime(idea.updated_at);

  const tag = document.createElement("span");
  tag.className = "card-status-tag";
  tag.textContent = idea.status;
  meta.appendChild(time);
  meta.appendChild(tag);
  card.appendChild(meta);

  card.addEventListener("click", (e) => {
    if (e.shiftKey && focusId !== null) {
      extendRangeTo(idea.id);
    } else {
      selectCard(idea.id);
    }
  });
  card.addEventListener("dblclick", () => openModal(idea.id));

  card.draggable = true;
  card.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", String(idea.id));
    e.dataTransfer.effectAllowed = "move";
    requestAnimationFrame(() => card.classList.add("dragging"));
  });
  card.addEventListener("dragend", () => card.classList.remove("dragging"));

  return card;
}

function buildEditField(idea) {
  const textarea = document.createElement("textarea");
  textarea.className = "card-edit";
  textarea.value = idea.text;

  textarea.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      commitEdit(idea.id, textarea.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelEdit();
    }
  });
  textarea.addEventListener("blur", () => {
    if (editingId === idea.id) commitEdit(idea.id, textarea.value);
  });

  requestAnimationFrame(() => {
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  });

  return textarea;
}

function render() {
  flatOrder = [];

  for (const status of STATUSES) {
    const container = document.getElementById(`cards-${status}`);
    container.innerHTML = "";

    const columnIdeas = ideas.filter((i) => i.status === status);

    if (columnIdeas.length === 0) {
      const hint = document.createElement("div");
      hint.className = "empty-hint";
      hint.textContent = "—";
      container.appendChild(hint);
      continue;
    }

    for (const idea of columnIdeas) {
      container.appendChild(buildCard(idea));
      flatOrder.push(idea.id);
    }
  }
}

// ---- selection: single focus, optional multi-select ("visual") range ----

function updateSelectionClasses() {
  document.querySelectorAll(".card").forEach((el) => {
    const id = Number(el.dataset.id);
    el.classList.toggle("selected", id === focusId);
    el.classList.toggle("in-range", selectedIds.has(id) && id !== focusId);
  });
  updateModeIndicator();
}

function updateModeIndicator() {
  if (visualAnchorId !== null && selectedIds.size > 1) {
    modeIndicator.textContent = `${selectedIds.size} selected — a/q/h/f/x/d apply to all, Esc cancels`;
    modeIndicator.hidden = false;
  } else {
    modeIndicator.hidden = true;
  }
}

function selectCard(id) {
  focusId = id;
  selectedIds = new Set([id]);
  visualAnchorId = null;
  updateSelectionClasses();
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

function extendRangeTo(id) {
  if (visualAnchorId === null) visualAnchorId = focusId;
  focusId = id;
  recomputeRange();
}

function recomputeRange() {
  const anchorIdx = flatOrder.indexOf(visualAnchorId);
  const focusIdx = flatOrder.indexOf(focusId);
  const lo = Math.min(anchorIdx, focusIdx);
  const hi = Math.max(anchorIdx, focusIdx);
  selectedIds = new Set(flatOrder.slice(lo, hi + 1));
  updateSelectionClasses();
  const el = document.querySelector(`.card[data-id="${focusId}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

function moveFocus(direction) {
  if (flatOrder.length === 0) return;
  const idx = flatOrder.indexOf(focusId);
  const nextIdx = idx === -1 ? 0 : Math.min(Math.max(idx + direction, 0), flatOrder.length - 1);
  focusId = flatOrder[nextIdx];

  if (visualAnchorId !== null) {
    recomputeRange();
  } else {
    selectedIds = new Set([focusId]);
    updateSelectionClasses();
    const el = document.querySelector(`.card[data-id="${focusId}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }
}

function toggleVisualMode() {
  if (focusId === null) return;
  if (visualAnchorId === null) {
    visualAnchorId = focusId;
    updateSelectionClasses();
  } else {
    visualAnchorId = null;
    selectedIds = new Set([focusId]);
    updateSelectionClasses();
  }
}

function exitVisualMode() {
  visualAnchorId = null;
  selectedIds = focusId === null ? new Set() : new Set([focusId]);
  updateSelectionClasses();
}

// ---- data operations ----

async function fetchIdeas() {
  const res = await fetch("/api/ideas");
  ideas = await res.json();
  render();
  if (focusId === null && flatOrder.length > 0) {
    selectCard(flatOrder[0]);
  }
  renderGoalAddIdeaChips();
  if (currentScreen === "goals") renderGoalsPanel(); // refresh goal rows' idea-link chips
}

// Shared idea-linking widget: a chip per already-linked idea (label + a
// remove ×) plus a "+ link idea" dropdown to add another -- a goal can
// link to more than one idea, so this is always a set, never a single
// select. Used by the goal-add form (local state, goal doesn't exist yet)
// and every goal row -- current or completed alike, since a past/completed
// goal should be linkable too, not just an active one -- which call the
// link/unlink API immediately instead via onAdd/onRemove. onJump is
// omitted for the add-form (nothing to jump to yet).
function buildIdeaChipsRow(linkedIdeas, { onAdd, onRemove, onJump }) {
  const wrap = document.createElement("div");
  wrap.className = "goal-idea-chips";

  for (const idea of linkedIdeas) {
    const chip = document.createElement("span");
    chip.className = "goal-idea-chip";

    const label = document.createElement(onJump ? "button" : "span");
    label.className = "goal-idea-chip-label";
    label.textContent = idea.text.length <= 30 ? idea.text : idea.text.slice(0, 27) + "...";
    label.title = idea.text;
    if (onJump) {
      label.type = "button";
      label.title = "jump to this idea on the board";
      label.addEventListener("click", () => onJump(idea.id));
    }
    chip.appendChild(label);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "goal-idea-chip-remove";
    removeBtn.textContent = "×";
    removeBtn.title = "unlink this idea";
    removeBtn.addEventListener("click", () => onRemove(idea.id));
    chip.appendChild(removeBtn);

    wrap.appendChild(chip);
  }

  const linkedIds = new Set(linkedIdeas.map((i) => i.id));
  const addSelect = document.createElement("select");
  addSelect.className = "goal-idea-add-select";
  addSelect.innerHTML = '<option value="">+ link idea</option>';
  for (const idea of ideas) {
    if (linkedIds.has(idea.id)) continue;
    const opt = document.createElement("option");
    opt.value = idea.id;
    opt.textContent = idea.text.length <= 40 ? idea.text : idea.text.slice(0, 37) + "...";
    addSelect.appendChild(opt);
  }
  addSelect.addEventListener("change", () => {
    if (!addSelect.value) return;
    onAdd(Number(addSelect.value));
  });
  wrap.appendChild(addSelect);

  return wrap;
}

// ---- goals screen: its own full screen, not a side panel -- see
// showScreen() below for how it and the board screen are switched ----

const goalsBadge = document.getElementById("goals-badge");
const goalAddForm = document.getElementById("goal-add-form");
const goalAddText = document.getElementById("goal-add-text");
const goalAddIdeaChipsEl = document.getElementById("goal-add-idea-chips");
let goalAddIdeaIds = new Set();

function renderGoalAddIdeaChips() {
  goalAddIdeaChipsEl.innerHTML = "";
  const linkedIdeas = [...goalAddIdeaIds]
    .map((id) => ideas.find((i) => i.id === id))
    .filter(Boolean);
  goalAddIdeaChipsEl.appendChild(
    buildIdeaChipsRow(linkedIdeas, {
      onAdd: (ideaId) => {
        goalAddIdeaIds.add(ideaId);
        renderGoalAddIdeaChips();
      },
      onRemove: (ideaId) => {
        goalAddIdeaIds.delete(ideaId);
        renderGoalAddIdeaChips();
      },
    })
  );
}

const goalListEl = document.getElementById("goal-list");
const goalWeekdayPills = document.querySelectorAll(".goal-weekday-pill");
const goalAddDate = document.getElementById("goal-add-date");
const goalDateSmartDefaultInput = document.getElementById("goal-date-smart-default");
const goalDateCutoffHourInput = document.getElementById("goal-date-cutoff-hour");
let selectedGoalWeekdays = new Set();

let completedGoals = [];

async function fetchGoalsData() {
  const [goalsRes, streakRes, completedRes] = await Promise.all([
    fetch("/api/goals"),
    fetch("/api/goals/streak"),
    fetch("/api/goals/completed"),
  ]);
  const goalsPayload = await goalsRes.json();
  todaysGoals = goalsPayload.goals;
  streakInfo = await streakRes.json();
  completedGoals = await completedRes.json();
  renderGoalsBadge();
  if (currentScreen === "goals") renderGoalsPanel();
}

// ---- smart-default date: after a configurable cutoff hour (default 6pm),
// a new one-off goal's date field defaults to tomorrow instead of today --
// matches planning tomorrow's goals before closing the laptop for the
// night. Always just an editable default, never forced: updateGoalAddDateVisibility
// only fills the field when it's empty, so a value you've already typed or
// changed is never clobbered. Pure GUI/localStorage state, same as the
// theme toggle -- no CLI equivalent, and none is needed. ----

const GOAL_DATE_SMART_DEFAULT_KEY = "idea-bank-goal-date-smart-default";
const GOAL_DATE_CUTOFF_HOUR_KEY = "idea-bank-goal-date-cutoff-hour";
const DEFAULT_GOAL_DATE_CUTOFF_HOUR = 18;

function loadGoalDateSettings() {
  let smartDefault = true;
  let cutoffHour = DEFAULT_GOAL_DATE_CUTOFF_HOUR;
  try {
    const storedEnabled = localStorage.getItem(GOAL_DATE_SMART_DEFAULT_KEY);
    if (storedEnabled !== null) smartDefault = storedEnabled !== "off";
    const storedCutoffRaw = localStorage.getItem(GOAL_DATE_CUTOFF_HOUR_KEY);
    const storedCutoff = Number(storedCutoffRaw);
    if (storedCutoffRaw !== null && Number.isInteger(storedCutoff) && storedCutoff >= 0 && storedCutoff <= 23) {
      cutoffHour = storedCutoff;
    }
  } catch {
    // localStorage unavailable (private browsing, etc.) -- just the defaults above
  }
  goalDateSmartDefaultInput.checked = smartDefault;
  goalDateCutoffHourInput.value = cutoffHour;
  return { smartDefault, cutoffHour };
}

function saveGoalDateSettings() {
  try {
    localStorage.setItem(GOAL_DATE_SMART_DEFAULT_KEY, goalDateSmartDefaultInput.checked ? "on" : "off");
    localStorage.setItem(GOAL_DATE_CUTOFF_HOUR_KEY, goalDateCutoffHourInput.value);
  } catch {
    // won't persist across reloads, but still applies for the rest of this session
  }
}

function computeSmartDefaultDate() {
  const { smartDefault, cutoffHour } = loadGoalDateSettings();
  const target = new Date();
  if (smartDefault && target.getHours() >= cutoffHour) target.setDate(target.getDate() + 1);
  const y = target.getFullYear();
  const m = String(target.getMonth() + 1).padStart(2, "0");
  const d = String(target.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function updateGoalAddDateVisibility() {
  const oneOff = selectedGoalWeekdays.size === 0;
  goalAddDate.hidden = !oneOff;
  if (oneOff && !goalAddDate.value) goalAddDate.value = computeSmartDefaultDate();
}

goalWeekdayPills.forEach((pill) => {
  pill.addEventListener("click", () => {
    const day = Number(pill.dataset.weekday);
    pill.classList.toggle("selected");
    if (selectedGoalWeekdays.has(day)) selectedGoalWeekdays.delete(day);
    else selectedGoalWeekdays.add(day);
    updateGoalAddDateVisibility();
  });
});

goalDateSmartDefaultInput.addEventListener("change", saveGoalDateSettings);
goalDateCutoffHourInput.addEventListener("change", saveGoalDateSettings);

function renderGoalsBadge() {
  goalsBadge.textContent = `${streakInfo.today_done}/${streakInfo.today_total}`;
  goalsBadge.classList.toggle("complete", streakInfo.today_complete);
}

function renderGoalsPanel() {
  document.getElementById("goal-streak").textContent = `streak ${streakInfo.streak}d`;
  document.getElementById("goal-streak").classList.toggle("active", streakInfo.streak > 0);
  document.getElementById("goal-longest").textContent = `best ${streakInfo.longest}d`;
  document.getElementById("goal-xp").textContent = `${streakInfo.xp}xp`;

  goalListEl.innerHTML = "";
  if (todaysGoals.length === 0) {
    const hint = document.createElement("div");
    hint.className = "goals-empty-hint";
    hint.textContent = "no goals due today -- add one below";
    goalListEl.appendChild(hint);
    return;
  }

  for (const goal of todaysGoals) {
    goalListEl.appendChild(buildGoalRow(goal));
  }

  renderGoalHistory();
}

const goalHistoryListEl = document.getElementById("goal-history-list");

function renderGoalHistory() {
  goalHistoryListEl.innerHTML = "";
  if (completedGoals.length === 0) {
    const hint = document.createElement("div");
    hint.className = "goals-empty-hint";
    hint.textContent = "nothing completed yet -- it'll show up here once you do";
    goalHistoryListEl.appendChild(hint);
    return;
  }
  for (const goal of completedGoals) {
    goalHistoryListEl.appendChild(buildGoalHistoryRow(goal));
  }
}

function buildGoalHistoryRow(goal) {
  const row = document.createElement("div");
  row.className = "goal-history-row";

  const text = document.createElement("div");
  text.className = "goal-history-text";
  text.textContent = goal.text;
  row.appendChild(text);

  const meta = document.createElement("div");
  meta.className = "goal-history-meta";

  const tag = document.createElement("span");
  tag.className = "goal-tag";
  tag.textContent = formatWeekdays(goal.weekdays);
  meta.appendChild(tag);

  const countTag = document.createElement("span");
  countTag.className = "goal-tag";
  countTag.textContent = `${goal.times_completed}x`;
  meta.appendChild(countTag);

  const when = goal.last_completed || goal.archived_at;
  if (when) {
    const whenTag = document.createElement("span");
    whenTag.className = "goal-tag";
    whenTag.textContent = when;
    meta.appendChild(whenTag);
  }

  row.appendChild(meta);

  // Completed goals stay linkable too -- a past goal is still valid
  // evidence of progress toward an idea you only later decided it served.
  row.appendChild(
    buildIdeaChipsRow(goal.ideas, {
      onAdd: (ideaId) => linkGoalToIdea(goal.id, ideaId),
      onRemove: (ideaId) => unlinkGoalFromIdea(goal.id, ideaId),
      onJump: (ideaId) => {
        showScreen("board");
        selectCard(ideaId);
      },
    })
  );

  return row;
}

const WEEKDAY_DISPLAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatWeekdays(weekdays) {
  if (!weekdays) return "one-off";
  const days = new Set(weekdays);
  if (days.size === 7) return "daily";
  if (days.size === 5 && [0, 1, 2, 3, 4].every((d) => days.has(d))) return "weekdays";
  if (days.size === 2 && days.has(5) && days.has(6)) return "weekends";
  return [...days].sort((a, b) => a - b).map((d) => WEEKDAY_DISPLAY[d]).join("/");
}

function buildGoalRow(goal) {
  const row = document.createElement("div");
  row.className = "goal-row" + (goal.completed_at ? " done" : "");

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "goal-check";
  check.checked = Boolean(goal.completed_at);
  check.addEventListener("change", () => setGoalDone(goal.id, check.checked));

  const body = document.createElement("div");
  body.className = "goal-row-body";

  const text = document.createElement("div");
  text.className = "goal-row-text";
  text.textContent = goal.text;
  body.appendChild(text);

  const meta = document.createElement("div");
  meta.className = "goal-row-meta";

  const recurTag = document.createElement("span");
  recurTag.className = "goal-tag";
  recurTag.textContent = formatWeekdays(goal.weekdays);
  meta.appendChild(recurTag);

  meta.appendChild(
    buildIdeaChipsRow(goal.ideas, {
      onAdd: (ideaId) => linkGoalToIdea(goal.id, ideaId),
      onRemove: (ideaId) => unlinkGoalFromIdea(goal.id, ideaId),
      onJump: (ideaId) => {
        showScreen("board");
        selectCard(ideaId);
      },
    })
  );
  body.appendChild(meta);

  const actions = document.createElement("div");
  actions.className = "goal-row-actions";
  if (goal.weekdays) {
    const stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.textContent = "stop";
    stopBtn.title = "stop this recurring goal (keeps its history)";
    stopBtn.addEventListener("click", () => stopGoal(goal.id));
    actions.appendChild(stopBtn);
  }
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.textContent = "×";
  removeBtn.title = "delete this goal and its history";
  removeBtn.addEventListener("click", () => removeGoal(goal.id));
  actions.appendChild(removeBtn);

  row.appendChild(check);
  row.appendChild(body);
  row.appendChild(actions);
  return row;
}

async function setGoalDone(goalId, completed) {
  await fetch(`/api/goals/${goalId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ completed }),
  });
  await fetchGoalsData();
}

async function stopGoal(goalId) {
  await fetch(`/api/goals/${goalId}/stop`, { method: "POST" });
  await fetchGoalsData();
}

async function removeGoal(goalId) {
  if (!window.confirm("Delete this goal and its history? This can't be undone.")) return;
  await fetch(`/api/goals/${goalId}`, { method: "DELETE" });
  await fetchGoalsData();
}

async function linkGoalToIdea(goalId, ideaId) {
  await fetch(`/api/goals/${goalId}/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea_id: ideaId }),
  });
  await fetchGoalsData();
}

async function unlinkGoalFromIdea(goalId, ideaId) {
  await fetch(`/api/goals/${goalId}/unlink`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea_id: ideaId }),
  });
  await fetchGoalsData();
}

goalAddForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = goalAddText.value.trim();
  if (!text) return;
  const weekdays = [...selectedGoalWeekdays];
  const payload = { text, idea_ids: [...goalAddIdeaIds] };
  if (weekdays.length > 0) payload.weekdays = weekdays;
  else if (goalAddDate.value) payload.target_date = goalAddDate.value;

  const res = await fetch("/api/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) return;

  goalAddText.value = "";
  selectedGoalWeekdays.clear();
  goalWeekdayPills.forEach((p) => p.classList.remove("selected"));
  goalAddDate.value = "";
  goalAddIdeaIds.clear();
  renderGoalAddIdeaChips();
  updateGoalAddDateVisibility(); // refills with a fresh smart default for the next add
  await fetchGoalsData();
  goalAddText.focus();
});

// ---- screens: goals and board are full-screen sibling sections, switched
// by the top-bar tabs (or g/i) -- goals is the default on load. Both stay
// fetched regardless of which is visible, so switching is instant. ----

const screenTabs = document.querySelectorAll(".screen-tab");
const goalsScreenEl = document.getElementById("goals-screen");
const boardScreenEl = document.getElementById("board-screen");
let currentScreen = "goals";

function showScreen(name) {
  currentScreen = name;
  goalsScreenEl.hidden = name !== "goals";
  boardScreenEl.hidden = name !== "board";
  screenTabs.forEach((tab) => {
    const active = tab.dataset.screen === name;
    tab.classList.toggle("selected", active);
    tab.setAttribute("aria-selected", String(active));
  });
  if (name === "goals") {
    renderGoalAddIdeaChips();
    renderGoalsPanel();
    updateGoalAddDateVisibility();
  }
}

screenTabs.forEach((tab) => {
  tab.addEventListener("click", () => showScreen(tab.dataset.screen));
});

// ---- idea-add form: a labeled GUI box on the board screen, not a bare
// command-prompt input. Status pills are scoped to this form's own
// container (never a bare document-wide ".target-pill" query) so they
// can't collide with any other pill group on the page -- see the
// goal-weekday-pill bug this same mistake caused earlier. ----

const ideaAddForm = document.getElementById("idea-add-form");
const ideaAddText = document.getElementById("idea-add-text");
const ideaAddStatusPills = document.querySelectorAll("#idea-add-status .idea-status-pill");
let ideaAddStatus = "inbox";

ideaAddStatusPills.forEach((pill) => {
  pill.addEventListener("click", () => {
    ideaAddStatus = pill.dataset.status;
    ideaAddStatusPills.forEach((p) => p.classList.toggle("selected", p === pill));
  });
});

async function createIdea(text, status) {
  const res = await fetch("/api/ideas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, status }),
  });
  if (!res.ok) return;
  const created = await res.json();
  ideas.unshift(created);
  render();
}

ideaAddForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = ideaAddText.value.trim();
  if (!text) return;
  ideaAddText.value = "";
  createIdea(text, ideaAddStatus);
  ideaAddText.focus();
});

async function patchIdea(id, payload) {
  const res = await fetch(`/api/ideas/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function deleteIdeaRequest(id) {
  const res = await fetch(`/api/ideas/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(await res.text());
}

// single-card move: the one deliberate motion moment (FLIP-animated slide)
async function moveIdeaAnimated(id, status) {
  const idea = ideas.find((i) => i.id === id);
  if (!idea || idea.status === status) return;

  const el = document.querySelector(`.card[data-id="${id}"]`);
  const before = el ? el.getBoundingClientRect() : null;
  const prevStatus = idea.status;

  idea.status = status;
  render();
  updateSelectionClasses();

  const after = document.querySelector(`.card[data-id="${id}"]`);
  if (before && after && !reduceMotion()) {
    const nowRect = after.getBoundingClientRect();
    const dx = before.left - nowRect.left;
    const dy = before.top - nowRect.top;
    if (dx || dy) {
      after.style.transition = "none";
      after.style.transform = `translate(${dx}px, ${dy}px)`;
      requestAnimationFrame(() => {
        after.style.transition = "transform 220ms ease";
        after.style.transform = "";
      });
    }
  }

  try {
    const updated = await patchIdea(id, { status });
    Object.assign(idea, updated);
  } catch (err) {
    console.error("failed to move idea, reverting", err);
    idea.status = prevStatus;
    render();
    updateSelectionClasses();
  }
}

async function applyStatusToSelected(status) {
  const ids = Array.from(selectedIds);
  if (ids.length === 0) return;

  if (ids.length === 1) {
    await moveIdeaAnimated(ids[0], status);
  } else {
    // batch: skip the per-card slide (would just look like visual noise
    // firing across several columns at once) and re-render once instead
    const results = await Promise.allSettled(ids.map((id) => patchIdea(id, { status })));
    results.forEach((r, i) => {
      if (r.status === "fulfilled") {
        const idea = ideas.find((x) => x.id === ids[i]);
        if (idea) Object.assign(idea, r.value);
      } else {
        console.error("failed to move idea", ids[i], r.reason);
      }
    });
    render();
  }

  exitVisualMode();
}

async function deleteSelected() {
  const ids = Array.from(selectedIds);
  if (ids.length === 0) return;
  const label = ids.length === 1 ? "this idea" : `these ${ids.length} ideas`;
  if (!window.confirm(`Delete ${label}? This can't be undone.`)) return;

  const priorIndex = flatOrder.indexOf(focusId);

  const results = await Promise.allSettled(ids.map((id) => deleteIdeaRequest(id)));
  const deletedIds = new Set(
    ids.filter((id, i) => results[i].status === "fulfilled")
  );
  results.forEach((r, i) => {
    if (r.status === "rejected") console.error("failed to delete idea", ids[i], r.reason);
  });

  ideas = ideas.filter((i) => !deletedIds.has(i.id));
  visualAnchorId = null;
  render();
  fetchGoalsData(); // any goal linked to a deleted idea just loses that link

  if (flatOrder.length > 0) {
    const nextIndex = Math.min(Math.max(priorIndex, 0), flatOrder.length - 1);
    selectCard(flatOrder[nextIndex]);
  } else {
    focusId = null;
    selectedIds = new Set();
    updateModeIndicator();
  }
}

function startEdit() {
  if (focusId === null || editingId !== null) return;
  visualAnchorId = null;
  selectedIds = new Set([focusId]);
  editingId = focusId;
  render();
  updateSelectionClasses();
}

function cancelEdit() {
  editingId = null;
  render();
  updateSelectionClasses();
}

async function commitEdit(id, newText) {
  editingId = null; // exit edit mode immediately either way
  const text = newText.trim();
  if (!text) {
    render();
    updateSelectionClasses();
    return;
  }
  const idea = ideas.find((i) => i.id === id);
  if (idea) idea.text = text;
  render();
  updateSelectionClasses();

  try {
    const updated = await patchIdea(id, { text });
    if (idea) Object.assign(idea, updated);
  } catch (err) {
    console.error("failed to save edit", err);
  }
}

// ---- drag and drop: drop zones are the 5 permanent column containers,
// wired once here since render() only ever replaces their children ----

document.querySelectorAll(".cards").forEach((container) => {
  container.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    container.classList.add("drag-over");
  });
  container.addEventListener("dragleave", () => {
    container.classList.remove("drag-over");
  });
  container.addEventListener("drop", (e) => {
    e.preventDefault();
    container.classList.remove("drag-over");
    const id = Number(e.dataTransfer.getData("text/plain"));
    const status = container.closest(".column").dataset.status;
    if (!id || !status) return;
    selectCard(id);
    moveIdeaAnimated(id, status);
  });
});

// ---- detail modal: click-to-open examine/edit view ----

let modalIdeaId = null;
let modalPending = null; // { text, status, fields: [[key, value], ...], notes }

const modalBackdrop = document.getElementById("modal-backdrop");
const modalStatusPills = document.getElementById("modal-status-pills");
const modalTextEl = document.getElementById("modal-text");
const modalFieldsEl = document.getElementById("modal-fields");
const modalGoalsEl = document.getElementById("modal-goals");
const modalNotesEl = document.getElementById("modal-notes");
const modalMetaEl = document.getElementById("modal-meta");

modalTextEl.addEventListener("input", () => {
  if (modalPending) modalPending.text = modalTextEl.value;
});
modalNotesEl.addEventListener("input", () => {
  if (modalPending) modalPending.notes = modalNotesEl.value;
});

function openModal(id) {
  const idea = ideas.find((i) => i.id === id);
  if (!idea) return;
  modalIdeaId = id;
  modalPending = {
    text: idea.text,
    status: idea.status,
    fields: Object.entries(idea.fields || {}),
    notes: idea.notes || "",
  };
  renderModal(idea);
  modalGoalsEl.innerHTML = ""; // clear the previous idea's goals while the fetch below is in flight
  renderModalGoals(id);
  modalBackdrop.hidden = false;
  requestAnimationFrame(() => modalTextEl.focus());
}

// Goals linked to this idea, split into "current" and "completed" groups --
// current gets the app's gold accent (same as an active idea/goal), completed
// gets teal + a strikethrough, mirroring how a completed goal row already
// reads on the goals screen.
async function renderModalGoals(ideaId) {
  const res = await fetch(`/api/ideas/${ideaId}/goals`);
  if (!res.ok || modalIdeaId !== ideaId) return; // modal moved on while this was in flight
  const goals = await res.json();
  if (modalIdeaId !== ideaId) return;

  modalGoalsEl.innerHTML = "";
  if (goals.length === 0) {
    const hint = document.createElement("div");
    hint.className = "modal-goals-empty";
    hint.textContent = "no goals linked to this idea yet";
    modalGoalsEl.appendChild(hint);
    return;
  }

  const current = goals.filter((g) => !g.completed);
  const completed = goals.filter((g) => g.completed);
  if (current.length) modalGoalsEl.appendChild(buildModalGoalGroup("current", current, false));
  if (completed.length) modalGoalsEl.appendChild(buildModalGoalGroup("completed", completed, true));
}

function buildModalGoalGroup(label, goals, completed) {
  const group = document.createElement("div");
  group.className = "modal-goal-group";

  const labelEl = document.createElement("div");
  labelEl.className = "modal-goal-group-label";
  labelEl.textContent = label;
  group.appendChild(labelEl);

  for (const goal of goals) {
    const row = document.createElement("div");
    row.className = "modal-goal-row" + (completed ? " completed" : "");

    const text = document.createElement("span");
    text.className = "modal-goal-text";
    text.textContent = goal.text;
    row.appendChild(text);

    const tag = document.createElement("span");
    tag.className = "goal-tag";
    tag.textContent = formatWeekdays(goal.weekdays);
    row.appendChild(tag);

    if (completed && goal.times_completed) {
      const count = document.createElement("span");
      count.className = "goal-tag";
      count.textContent = `${goal.times_completed}x`;
      row.appendChild(count);
    }

    group.appendChild(row);
  }
  return group;
}

function renderModal(idea) {
  modalTextEl.value = modalPending.text;
  modalNotesEl.value = modalPending.notes;
  modalMetaEl.textContent = `created ${idea.created_at}   updated ${idea.updated_at}`;

  modalStatusPills.innerHTML = "";
  for (const status of STATUSES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "target-pill" + (status === modalPending.status ? " selected" : "");
    btn.dataset.status = status;
    btn.textContent = status;
    btn.addEventListener("click", () => {
      modalPending.status = status;
      renderModal(idea);
    });
    modalStatusPills.appendChild(btn);
  }

  renderModalFields();
}

function renderModalFields() {
  modalFieldsEl.innerHTML = "";
  modalPending.fields.forEach(([key, value], index) => {
    const row = document.createElement("div");
    row.className = "field-row";

    const keyInput = document.createElement("input");
    keyInput.className = "field-key";
    keyInput.type = "text";
    keyInput.placeholder = "key";
    keyInput.value = key;
    keyInput.addEventListener("input", () => {
      modalPending.fields[index][0] = keyInput.value;
    });

    const sep = document.createElement("span");
    sep.className = "field-sep";
    sep.textContent = ":";

    const valueInput = document.createElement("input");
    valueInput.className = "field-value";
    valueInput.type = "text";
    valueInput.placeholder = "value";
    valueInput.value = value;
    valueInput.addEventListener("input", () => {
      modalPending.fields[index][1] = valueInput.value;
    });

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "field-row-remove";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      modalPending.fields.splice(index, 1);
      renderModalFields();
    });

    row.appendChild(keyInput);
    row.appendChild(sep);
    row.appendChild(valueInput);
    row.appendChild(removeBtn);
    modalFieldsEl.appendChild(row);
  });
}

document.getElementById("modal-add-field").addEventListener("click", () => {
  modalPending.fields.push(["", ""]);
  renderModalFields();
  const lastRow = modalFieldsEl.querySelector(".field-row:last-child input");
  if (lastRow) lastRow.focus();
});

async function closeModal(save) {
  const id = modalIdeaId;
  const pending = modalPending;
  modalBackdrop.hidden = true;
  modalIdeaId = null;
  modalPending = null;
  if (!save || id === null) return;

  const idea = ideas.find((i) => i.id === id);
  if (!idea) return;

  const fieldsObj = {};
  for (const [key, value] of pending.fields) {
    const trimmedKey = key.trim();
    if (trimmedKey) fieldsObj[trimmedKey] = value;
  }
  const trimmedText = pending.text.trim();

  const payload = { fields: fieldsObj };
  if (trimmedText) payload.text = trimmedText;
  if (pending.status !== idea.status) payload.status = pending.status;
  if (pending.notes !== (idea.notes || "")) payload.notes = pending.notes || null;

  try {
    const updated = await patchIdea(id, payload);
    Object.assign(idea, updated);
    render();
    updateSelectionClasses();
  } catch (err) {
    console.error("failed to save idea", err);
  }
}

document.getElementById("modal-close").addEventListener("click", () => closeModal(true));
document.getElementById("modal-done").addEventListener("click", () => closeModal(true));
modalBackdrop.addEventListener("click", (e) => {
  if (e.target === modalBackdrop) closeModal(true);
});

document.getElementById("modal-popout").addEventListener("click", () => {
  if (modalIdeaId === null) return;
  // a per-id window name so popping out several ideas opens separate
  // windows instead of one replacing another
  window.open(`/idea.html?id=${modalIdeaId}`, `idea-${modalIdeaId}`, "width=560,height=680");
});

document.getElementById("modal-delete").addEventListener("click", async () => {
  if (modalIdeaId === null) return;
  if (!window.confirm("Delete this idea? This can't be undone.")) return;
  const id = modalIdeaId;
  modalBackdrop.hidden = true;
  modalIdeaId = null;
  modalPending = null;

  try {
    await deleteIdeaRequest(id);
  } catch (err) {
    console.error("failed to delete idea", err);
    return;
  }
  ideas = ideas.filter((i) => i.id !== id);
  render();
  fetchGoalsData(); // any goal linked to a deleted idea just loses that link
  if (flatOrder.length > 0) {
    selectCard(flatOrder[0]);
  } else {
    focusId = null;
    selectedIds = new Set();
    updateModeIndicator();
  }
});

// ---- keyboard ----

document.addEventListener("keydown", (e) => {
  if (!modalBackdrop.hidden) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeModal(false); // Escape discards, matching the inline-edit convention
    }
    return; // let typing in the modal's own fields behave normally otherwise
  }

  const activeTag = document.activeElement && document.activeElement.tagName;
  const inTextField = activeTag === "INPUT" || activeTag === "TEXTAREA";

  if (inTextField) {
    if (e.key === "Escape") document.activeElement.blur();
    return;
  }

  switch (e.key) {
    case "j":
    case "ArrowDown":
      e.preventDefault();
      moveFocus(1);
      break;
    case "k":
    case "ArrowUp":
      e.preventDefault();
      moveFocus(-1);
      break;
    case "a":
      applyStatusToSelected("active");
      break;
    case "q":
      applyStatusToSelected("queued");
      break;
    case "x":
      applyStatusToSelected("archive");
      break;
    case "h":
      applyStatusToSelected("horizon");
      break;
    case "f":
      applyStatusToSelected("frontier");
      break;
    case "g":
      showScreen("goals");
      break;
    case "i":
      showScreen("board");
      break;
    case "v":
      toggleVisualMode();
      break;
    case "e":
      startEdit();
      break;
    case "Enter":
      if (focusId !== null && editingId === null) {
        e.preventDefault();
        openModal(focusId);
      }
      break;
    case "d":
    case "Delete":
    case "Backspace":
      deleteSelected();
      break;
    case "Escape":
      if (visualAnchorId !== null) exitVisualMode();
      break;
  }
});

window.addEventListener("load", () => {
  if (window.location.hash === "#horizon") {
    showScreen("board");
    const col = document.querySelector('.column[data-status="horizon"]');
    if (col) col.scrollIntoView({ inline: "start" });
  }
});

// keep relative timestamps fresh without a full re-render
setInterval(() => {
  document.querySelectorAll(".card").forEach((el) => {
    const idea = ideas.find((i) => i.id === Number(el.dataset.id));
    const timeEl = el.querySelector(".card-time");
    if (idea && timeEl) timeEl.textContent = relativeTime(idea.updated_at);
  });
}, 30000);

// ---- auto-refresh: re-pull ideas/goals periodically so a window left open
// a while (e.g. the desktop launcher's dedicated window) doesn't drift from
// changes made elsewhere -- another window, or the CLI. Skips the ideas
// half while a card is being inline-edited (editingId set), since fetchIdeas
// -> render() would rebuild that card's textarea from server data and wipe
// out whatever's been typed but not yet committed; the goals screen has no
// equivalent in-place-edit state, so it always refreshes. Pure GUI polling,
// nothing to script against -- the same exception as the theme toggle. ----
const AUTO_REFRESH_INTERVAL_MS = 90000;
setInterval(() => {
  if (editingId === null) fetchIdeas();
  fetchGoalsData();
}, AUTO_REFRESH_INTERVAL_MS);

showScreen("goals");
fetchIdeas();
fetchGoalsData();
