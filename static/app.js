const STATUSES = ["inbox", "active", "queued", "horizon", "frontier", "archive"];

let ideas = [];
let flatOrder = [];

let focusId = null; // the keyboard "cursor" position
let selectedIds = new Set(); // ids batch actions apply to (always includes focusId)
let visualAnchorId = null; // non-null while range-select ("visual") mode is active
let editingId = null; // id of the card currently being text-edited, if any
let captureTargetStatus = "inbox";

// idea_id -> today's goal row, if tagged. A goal completes itself the
// moment its idea's status differs from status_at_tag (see dbutil.py) --
// the GUI never sets completed_at directly, only tags/untags.
let goalsToday = new Map();
let streakInfo = { streak: 0, longest: 0, today_complete: false, today_done: 0, today_total: 0, xp: 0 };

const captureForm = document.getElementById("capture-form");
const captureInput = document.getElementById("capture-input");
const modeIndicator = document.getElementById("mode-indicator");

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

  const goal = goalsToday.get(idea.id);
  const goalMarker = document.createElement("span");
  goalMarker.className = "goal-marker" + (goal ? (goal.completed_at ? " done" : " tagged") : "");
  goalMarker.textContent = goal ? (goal.completed_at ? "done" : "goal") : "goal";
  goalMarker.title = goal ? "tagged as today's goal -- click to untag" : "tag as today's goal";
  goalMarker.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleGoalForIdea(idea.id);
  });

  const tag = document.createElement("span");
  tag.className = "card-status-tag";
  tag.textContent = idea.status;
  meta.appendChild(time);
  meta.appendChild(goalMarker);
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
    modeIndicator.textContent = `${selectedIds.size} selected — a/q/h/x/d apply to all, Esc cancels`;
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
}

// ---- daily goals: subtle streak/xp readout in the top bar ----

async function fetchGoalState() {
  const [goalsRes, streakRes] = await Promise.all([
    fetch("/api/goals"),
    fetch("/api/goals/streak"),
  ]);
  const goalsPayload = await goalsRes.json();
  streakInfo = await streakRes.json();
  goalsToday = new Map(goalsPayload.goals.map((g) => [g.idea_id, g]));
  renderGoalReadout();
  // deliberately doesn't re-render the board here: a status change calls
  // this mid-FLIP-animation (see moveIdeaAnimated), and rebuilding card DOM
  // would cut the slide short. Card goal markers pick up the latest state
  // on the next render() a user action triggers anyway.
}

function renderGoalReadout() {
  const streakEl = document.getElementById("goal-streak");
  const labelEl = document.getElementById("goal-today-label");
  const fillEl = document.getElementById("goal-bar-fill");
  const xpEl = document.getElementById("goal-xp");

  streakEl.textContent = `streak ${streakInfo.streak}d`;
  streakEl.classList.toggle("active", streakInfo.streak > 0);
  xpEl.textContent = `${streakInfo.xp}xp`;

  if (streakInfo.today_total === 0) {
    labelEl.textContent = "no goals today";
    fillEl.style.width = "0%";
  } else {
    labelEl.textContent = `today ${streakInfo.today_done}/${streakInfo.today_total}`;
    fillEl.style.width = `${Math.round((streakInfo.today_done / streakInfo.today_total) * 100)}%`;
  }
}

// targeted DOM patch for one card's marker -- used after a status change so
// the "done" state appears without a full render() interrupting the FLIP
// slide that triggered it (see moveIdeaAnimated)
function updateCardGoalMarker(id) {
  const markerEl = document.querySelector(`.card[data-id="${id}"] .goal-marker`);
  if (!markerEl) return;
  const goal = goalsToday.get(id);
  markerEl.className = "goal-marker" + (goal ? (goal.completed_at ? " done" : " tagged") : "");
  markerEl.textContent = goal ? (goal.completed_at ? "done" : "goal") : "goal";
  markerEl.title = goal ? "tagged as today's goal -- click to untag" : "tag as today's goal";
}

async function setGoalTagged(id, tagged) {
  if (tagged) {
    await fetch("/api/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea_id: id }),
    });
  } else {
    await fetch(`/api/goals/${id}`, { method: "DELETE" });
  }
}

async function toggleGoalForIdea(id) {
  await setGoalTagged(id, !goalsToday.has(id));
  await fetchGoalState();
  render();
  updateSelectionClasses();
}

// batch g: if every selected card is already tagged, untag them all;
// otherwise tag whichever aren't yet (fills the gaps rather than toggling
// each independently, so one keypress reaches a consistent end state)
async function toggleGoalForSelected() {
  const ids = Array.from(selectedIds);
  if (ids.length === 0) return;
  const allTagged = ids.every((id) => goalsToday.has(id));
  await Promise.allSettled(ids.map((id) => setGoalTagged(id, !allTagged)));
  await fetchGoalState();
  render();
  updateSelectionClasses();
}

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
    fetchGoalState().then(() => updateCardGoalMarker(id)); // a status change may have just completed a goal
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
    fetchGoalState().then(() => ids.forEach(updateCardGoalMarker));
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
  fetchGoalState(); // server cascades goal rows on delete

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
  modalBackdrop.hidden = false;
  requestAnimationFrame(() => modalTextEl.focus());
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
    keyInput.type = "text";
    keyInput.placeholder = "key";
    keyInput.value = key;
    keyInput.addEventListener("input", () => {
      modalPending.fields[index][0] = keyInput.value;
    });

    const valueInput = document.createElement("input");
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
    if (payload.status) fetchGoalState().then(() => updateCardGoalMarker(id)); // may have just completed a goal
  } catch (err) {
    console.error("failed to save idea", err);
  }
}

document.getElementById("modal-close").addEventListener("click", () => closeModal(true));
document.getElementById("modal-done").addEventListener("click", () => closeModal(true));
modalBackdrop.addEventListener("click", (e) => {
  if (e.target === modalBackdrop) closeModal(true);
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
  fetchGoalState(); // server cascades goal rows on delete
  if (flatOrder.length > 0) {
    selectCard(flatOrder[0]);
  } else {
    focusId = null;
    selectedIds = new Set();
    updateModeIndicator();
  }
});

// ---- capture ----

function setCaptureTarget(status) {
  captureTargetStatus = status;
  document.querySelectorAll(".target-pill").forEach((btn) => {
    btn.classList.toggle("selected", btn.dataset.status === status);
  });
}

document.querySelectorAll(".target-pill").forEach((btn) => {
  btn.addEventListener("click", () => setCaptureTarget(btn.dataset.status));
});

captureForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = captureInput.value.trim();
  if (!text) return;
  captureInput.value = "";
  createIdea(text, captureTargetStatus);
  setCaptureTarget("inbox"); // reset for the next capture, like the CLI's per-call default
  captureInput.focus();
});

// ---- keyboard ----

const ALT_STATUS_KEYS = { i: "inbox", a: "active", q: "queued", h: "horizon", f: "frontier", x: "archive" };

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
    if (e.altKey && document.activeElement === captureInput) {
      const status = ALT_STATUS_KEYS[e.key.toLowerCase()];
      if (status) {
        e.preventDefault();
        setCaptureTarget(status);
      }
    }
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
      toggleGoalForSelected();
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
    case "/":
      e.preventDefault();
      captureInput.focus();
      break;
  }
});

window.addEventListener("load", () => {
  if (window.location.hash === "#horizon") {
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

fetchIdeas();
fetchGoalState().then(() => {
  render(); // picks up each card's goal marker once the first fetch lands
  updateSelectionClasses();
});
