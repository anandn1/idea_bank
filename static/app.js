const STATUSES = ["inbox", "active", "queued", "horizon", "archive"];

let ideas = [];
let selectedId = null;
let flatOrder = [];

const captureForm = document.getElementById("capture-form");
const captureInput = document.getElementById("capture-input");

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

function buildCard(idea) {
  const card = document.createElement("div");
  card.className = "card" + (idea.id === selectedId ? " selected" : "");
  card.dataset.id = idea.id;
  card.dataset.status = idea.status;
  card.tabIndex = -1;

  const text = document.createElement("div");
  text.className = "card-text";
  text.textContent = idea.text;

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
  card.appendChild(text);
  card.appendChild(meta);

  card.addEventListener("click", () => selectCard(idea.id));

  return card;
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

function selectCard(id) {
  selectedId = id;
  document.querySelectorAll(".card").forEach((el) => {
    el.classList.toggle("selected", Number(el.dataset.id) === id);
  });
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

function selectNext() {
  if (flatOrder.length === 0) return;
  const idx = flatOrder.indexOf(selectedId);
  const next = idx === -1 ? 0 : Math.min(idx + 1, flatOrder.length - 1);
  selectCard(flatOrder[next]);
}

function selectPrev() {
  if (flatOrder.length === 0) return;
  const idx = flatOrder.indexOf(selectedId);
  const prev = idx === -1 ? 0 : Math.max(idx - 1, 0);
  selectCard(flatOrder[prev]);
}

async function fetchIdeas() {
  const res = await fetch("/api/ideas");
  ideas = await res.json();
  render();
  if (selectedId === null && flatOrder.length > 0) {
    selectCard(flatOrder[0]);
  }
}

async function createIdea(text) {
  const res = await fetch("/api/ideas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) return;
  const created = await res.json();
  ideas.unshift(created);
  render();
}

async function moveIdea(id, status) {
  const idea = ideas.find((i) => i.id === id);
  if (!idea || idea.status === status) return;

  const el = document.querySelector(`.card[data-id="${id}"]`);
  const before = el ? el.getBoundingClientRect() : null;
  const prevStatus = idea.status;

  idea.status = status;
  render();
  selectCard(id);

  // the one deliberate motion moment: FLIP the card into its new column
  const after = document.querySelector(`.card[data-id="${id}"]`);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (before && after && !reduceMotion) {
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
    const res = await fetch(`/api/ideas/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error(await res.text());
    const updated = await res.json();
    Object.assign(idea, updated);
  } catch (err) {
    console.error("failed to move idea, reverting", err);
    idea.status = prevStatus;
    render();
    selectCard(id);
  }
}

function moveSelected(status) {
  if (selectedId !== null) moveIdea(selectedId, status);
}

captureForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = captureInput.value.trim();
  if (!text) return;
  captureInput.value = "";
  createIdea(text);
  captureInput.focus();
});

document.addEventListener("keydown", (e) => {
  const activeTag = document.activeElement && document.activeElement.tagName;
  if (activeTag === "INPUT" || activeTag === "TEXTAREA") {
    if (e.key === "Escape") document.activeElement.blur();
    return;
  }

  switch (e.key) {
    case "j":
    case "ArrowDown":
      e.preventDefault();
      selectNext();
      break;
    case "k":
    case "ArrowUp":
      e.preventDefault();
      selectPrev();
      break;
    case "a":
      moveSelected("active");
      break;
    case "q":
      moveSelected("queued");
      break;
    case "x":
      moveSelected("archive");
      break;
    case "h":
      moveSelected("horizon");
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
