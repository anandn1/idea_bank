// Markdown for idea notes: vendored marked (GitHub-flavored markdown) for
// parsing, vendored DOMPurify for sanitizing the HTML it produces -- marked
// passes raw HTML in notes straight through, so its output is never put on
// the page unsanitized. See static/vendor/README.md for versions.
//
// Shared by app.js (the board's detail modal) and idea-view.js (the
// full-page idea view), along with createNotesEditor() for the read/edit toggle.
// Wrapped in its own scope so only `IdeaMarkdown` reaches the page's globals.

(() => {
const markedLib = typeof module !== "undefined" ? require("./vendor/marked.umd.js") : globalThis.marked;

// Note headings sit inside a modal that already has its own heading, so
// "# Title" renders as an h3 (and so on down), with the hashes kept as a
// dim marker -- the same look as the modal's own "# notes" label. Task
// items use the app's [ ]/[x] glyphs instead of native checkboxes.
const HEADING_LEVEL_OFFSET = 2;
const MAX_HEADING_LEVEL = 6;

const notesMarked = new markedLib.Marked({
  gfm: true,
  breaks: true, // a single newline is a line break, as typed
  renderer: {
    heading({ tokens, depth }) {
      const level = Math.min(depth + HEADING_LEVEL_OFFSET, MAX_HEADING_LEVEL);
      const marker = `<span class="md-h-mark" aria-hidden="true">${"#".repeat(depth)} </span>`;
      return `<h${level} class="md-h md-h${depth}">${marker}${this.parser.parseInline(tokens)}</h${level}>\n`;
    },
    checkbox({ checked }) {
      const glyph = checked ? "[x]" : "[ ]";
      const state = checked ? "done: " : "to do: ";
      return (
        `<span class="md-task-mark${checked ? " done" : ""}" aria-hidden="true">${glyph}</span>` +
        `<span class="sr-only">${state}</span>`
      );
    },
  },
});

// Unsanitized -- only for tests and for renderMarkdown below.
function markdownToHtml(source) {
  return notesMarked.parse(String(source || ""));
}

// On top of DOMPurify's defaults:
// - no form controls: a note can't post data anywhere or fake an input;
// - no id/name: they could shadow the page's own elements (a note's
//   <div id="view-notice">);
// - no inline styles, and only this renderer's own classes: a note can't
//   restyle or overlay the app;
// - nothing that loads from another site: opening a note would tell that
//   site you looked at it. Images may come from this app or a data: URI.
const SANITIZE_OPTIONS = {
  RETURN_DOM_FRAGMENT: true,
  FORBID_TAGS: [
    "form", "input", "button", "select", "option", "textarea", "label", "fieldset",
    "video", "audio", "source", "track", "picture", "image", "use", "style",
  ],
  FORBID_ATTR: ["id", "name", "form", "formaction", "style", "srcset", "ping", "poster", "background"],
};
const RENDERER_CLASSES = new Set([
  "md-h", "md-h1", "md-h2", "md-h3", "md-h4", "md-h5", "md-h6", "md-h-mark", "md-task-mark", "done", "sr-only",
]);
const SCHEME_OR_PROTOCOL_RELATIVE = /^([a-z][a-z0-9+.-]*:|\/\/)/i;

// This app's own paths, or embedded data -- never another site.
function isLocalImageSource(src) {
  return !SCHEME_OR_PROTOCOL_RELATIVE.test(src.trim()) || /^data:image\//i.test(src.trim());
}

function renderMarkdown(source) {
  return globalThis.DOMPurify.sanitize(markdownToHtml(source), SANITIZE_OPTIONS);
}

function keepOnlyRendererClasses(node) {
  if (!node.hasAttribute("class")) return;
  const kept = [...node.classList].filter((name) => RENDERER_CLASSES.has(name));
  if (kept.length) node.setAttribute("class", kept.join(" "));
  else node.removeAttribute("class");
}

// Links in notes open in a new window, never replacing the app itself.
function openLinksInNewWindow(node) {
  // nodeName, lower-cased: an <a> inside inline SVG reports "a", not "A"
  const href = node.nodeName.toLowerCase() === "a" ? node.getAttribute("href") : null;
  if (href && !href.startsWith("#")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
}

function dropRemoteImageSource(node) {
  if (node.nodeName.toLowerCase() !== "img") return;
  const src = node.getAttribute("src");
  if (src !== null && !isLocalImageSource(src)) node.removeAttribute("src");
}

if (globalThis.DOMPurify) {
  globalThis.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    keepOnlyRendererClasses(node);
    openLinksInNewWindow(node);
    dropRemoteImageSource(node);
  });
}

// ---- notes read/edit toggle ----
//
// Notes open in a rendered read view; the textarea only appears while
// editing (via the toggle button, or double-clicking the read view), and
// grows with its content instead of being a 2-row scroll box. Empty notes
// open straight into editing. The textarea stays the single source of
// truth -- callers keep listening to its "input" events as before.
// `onRender(viewEl)`, if given, runs after each render of the read view.

const NOTES_EDITOR_MIN_ROWS = 4;
const NOTES_EDITOR_MAX_HEIGHT_VH = 60;
const NOTES_EDITOR_BORDER_SLACK_PX = 4; // covers the 1.5px top+bottom border, so no scrollbar flickers in

function createNotesEditor({ viewEl, textareaEl, toggleEl, onRender }) {
  function fitTextarea() {
    textareaEl.style.height = "auto";
    const maxHeight = (window.innerHeight * NOTES_EDITOR_MAX_HEIGHT_VH) / 100;
    textareaEl.style.height = `${Math.min(textareaEl.scrollHeight + NOTES_EDITOR_BORDER_SLACK_PX, maxHeight)}px`;
  }

  function showRead() {
    viewEl.replaceChildren(renderMarkdown(textareaEl.value));
    if (onRender) onRender(viewEl);
    viewEl.hidden = false;
    textareaEl.hidden = true;
    toggleEl.textContent = "edit";
    toggleEl.setAttribute("aria-pressed", "false");
  }

  function showEdit({ focus }) {
    viewEl.hidden = true;
    textareaEl.hidden = false;
    textareaEl.rows = NOTES_EDITOR_MIN_ROWS;
    fitTextarea();
    toggleEl.textContent = "preview";
    toggleEl.setAttribute("aria-pressed", "true");
    if (focus) textareaEl.focus();
  }

  toggleEl.addEventListener("click", () => {
    if (textareaEl.hidden) showEdit({ focus: true });
    else showRead();
  });
  viewEl.addEventListener("dblclick", (e) => {
    if (!e.target.closest("a")) showEdit({ focus: true });
  });
  textareaEl.addEventListener("input", fitTextarea);

  return {
    setNotes(text) {
      textareaEl.value = text || "";
      if (textareaEl.value.trim()) showRead();
      else showEdit({ focus: false });
    },
  };
}

const api = { markdownToHtml, renderMarkdown, createNotesEditor };
if (typeof module !== "undefined") module.exports = api;
else globalThis.IdeaMarkdown = api;
})();
