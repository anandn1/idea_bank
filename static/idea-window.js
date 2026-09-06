// Standalone idea editor, opened in its own window via the board modal's
// "pop out" button (see app.js's modal-popout handler). Deliberately not
// sharing code with app.js's openModal/renderModal/closeModal: this page
// has no board underneath it, no keyboard-driven card selection, and
// closes itself on save/delete instead of returning to a board view --
// different enough contexts that a shared abstraction would just be an
// if/else fork, not a real simplification.

const STATUSES = ["inbox", "active", "queued", "horizon", "frontier", "archive"];

const params = new URLSearchParams(window.location.search);
const ideaId = Number(params.get("id"));

let pending = null; // { text, status, fields: [[key, value], ...], notes }

const modalEl = document.querySelector(".modal");
const statusPillsEl = document.getElementById("modal-status-pills");
const textEl = document.getElementById("modal-text");
const fieldsEl = document.getElementById("modal-fields");
const notesEl = document.getElementById("modal-notes");
const metaEl = document.getElementById("modal-meta");

function showNotice(message) {
  modalEl.innerHTML = `<div class="standalone-notice">${message}</div>`;
}

async function load() {
  if (!ideaId) {
    showNotice("no idea id given");
    return;
  }
  const res = await fetch(`/api/ideas/${ideaId}`);
  if (!res.ok) {
    showNotice(res.status === 404 ? "this idea no longer exists" : "failed to load idea");
    return;
  }
  const idea = await res.json();
  document.title = idea.text.length <= 40 ? idea.text : idea.text.slice(0, 37) + "...";

  pending = {
    text: idea.text,
    status: idea.status,
    fields: Object.entries(idea.fields || {}),
    notes: idea.notes || "",
  };
  render(idea);
  textEl.focus();
}

function render(idea) {
  textEl.value = pending.text;
  notesEl.value = pending.notes;
  metaEl.textContent = `created ${idea.created_at}   updated ${idea.updated_at}`;

  statusPillsEl.innerHTML = "";
  for (const status of STATUSES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "target-pill" + (status === pending.status ? " selected" : "");
    btn.textContent = status;
    btn.addEventListener("click", () => {
      pending.status = status;
      render(idea);
    });
    statusPillsEl.appendChild(btn);
  }

  renderFields();
}

function renderFields() {
  fieldsEl.innerHTML = "";
  pending.fields.forEach(([key, value], index) => {
    const row = document.createElement("div");
    row.className = "field-row";

    const keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.placeholder = "key";
    keyInput.value = key;
    keyInput.addEventListener("input", () => {
      pending.fields[index][0] = keyInput.value;
    });

    const valueInput = document.createElement("input");
    valueInput.type = "text";
    valueInput.placeholder = "value";
    valueInput.value = value;
    valueInput.addEventListener("input", () => {
      pending.fields[index][1] = valueInput.value;
    });

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "field-row-remove";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      pending.fields.splice(index, 1);
      renderFields();
    });

    row.appendChild(keyInput);
    row.appendChild(valueInput);
    row.appendChild(removeBtn);
    fieldsEl.appendChild(row);
  });
}

document.getElementById("modal-add-field").addEventListener("click", () => {
  if (!pending) return;
  pending.fields.push(["", ""]);
  renderFields();
  const lastRow = fieldsEl.querySelector(".field-row:last-child input");
  if (lastRow) lastRow.focus();
});

textEl.addEventListener("input", () => {
  if (pending) pending.text = textEl.value;
});
notesEl.addEventListener("input", () => {
  if (pending) pending.notes = notesEl.value;
});

async function save() {
  const trimmedText = pending.text.trim();
  if (!trimmedText) return false;

  const fieldsObj = {};
  for (const [key, value] of pending.fields) {
    const trimmedKey = key.trim();
    if (trimmedKey) fieldsObj[trimmedKey] = value;
  }

  const res = await fetch(`/api/ideas/${ideaId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: trimmedText,
      status: pending.status,
      fields: fieldsObj,
      notes: pending.notes || null,
    }),
  });
  return res.ok;
}

document.getElementById("modal-done").addEventListener("click", async () => {
  if (!pending) return window.close();
  if (await save()) window.close();
});

document.getElementById("modal-close").addEventListener("click", () => window.close());

document.getElementById("modal-delete").addEventListener("click", async () => {
  if (!window.confirm("Delete this idea? This can't be undone.")) return;
  await fetch(`/api/ideas/${ideaId}`, { method: "DELETE" });
  window.close();
});

document.addEventListener("keydown", (e) => {
  const activeTag = document.activeElement && document.activeElement.tagName;
  if (e.key === "Escape" && activeTag !== "INPUT" && activeTag !== "TEXTAREA") {
    window.close();
  }
});

load();
