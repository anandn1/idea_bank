const STATUSES = ["inbox", "active", "queued", "horizon", "archive"];

let ideas = [];
let flatOrder = [];

let focusId = null; // the keyboard "cursor" position
let selectedIds = new Set(); // ids batch actions apply to (always includes focusId)
let visualAnchorId = null; // non-null while range-select ("visual") mode is active
let editingId = null; // id of the card currently being text-edited, if any
let captureTargetStatus = "inbox";

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

async function patchStatus(id, status) {
  const res = await fetch(`/api/ideas/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function patchText(id, text) {
  const res = await fetch(`/api/ideas/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
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
    const updated = await patchStatus(id, status);
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
    const results = await Promise.allSettled(ids.map((id) => patchStatus(id, status)));
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
    const updated = await patchText(id, text);
    if (idea) Object.assign(idea, updated);
  } catch (err) {
    console.error("failed to save edit", err);
  }
}

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

const ALT_STATUS_KEYS = { i: "inbox", a: "active", q: "queued", h: "horizon", x: "archive" };

document.addEventListener("keydown", (e) => {
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
    case "v":
      toggleVisualMode();
      break;
    case "e":
      startEdit();
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
