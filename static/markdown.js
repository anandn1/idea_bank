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
// "# Title" renders as an h3 (and so on down); the hashes themselves are
// not shown. Task items use the app's [ ]/[x] glyphs instead of native
// checkboxes.
const HEADING_LEVEL_OFFSET = 2;
const MAX_HEADING_LEVEL = 6;

function headingTag(depth) {
  return `h${Math.min(depth + HEADING_LEVEL_OFFSET, MAX_HEADING_LEVEL)}`;
}

const noteBlocks = typeof module !== "undefined" ? require("./note-blocks.js") : globalThis.IdeaNoteBlocks;

// ---- callouts ----
//
// GitHub's alert syntax: a quote whose first line is "[!WORD]" becomes a
// card ("> [!ALARM]" / "> fix it"), optionally titled after the marker as
// in Obsidian ("> [!ALARM] If you fall behind"). The word is free text; a
// few known ones pick a tone and symbol (see calloutStyle in note-blocks.js).
const CALLOUT_START = /^ {0,3}>[ \t]?\[!([A-Za-z][\w-]*)\][ \t]*([^\n]*)(?:\n|$)/;
const QUOTE_LINE = /^ {0,3}>[ \t]?(.*)(?:\n|$)/;

const callout = {
  name: "callout",
  level: "block",
  // Only where a line starts: marked passes `src` from mid-line positions too.
  start(src) {
    const match = /\n {0,3}>[ \t]?\[![A-Za-z]/.exec(src);
    return match ? match.index + 1 : undefined;
  },
  tokenizer(src) {
    const start = CALLOUT_START.exec(src);
    if (!start) return undefined;
    let raw = start[0];
    const body = [];
    for (;;) {
      const line = QUOTE_LINE.exec(src.slice(raw.length));
      if (!line || !line[0]) break;
      raw += line[0];
      body.push(line[1]);
    }
    return {
      type: "callout",
      raw,
      kind: start[1],
      titleTokens: this.lexer.inlineTokens(start[2].trim()),
      tokens: this.lexer.blockTokens(body.join("\n")),
    };
  },
  renderer({ kind, titleTokens, tokens }) {
    const { tone, glyph } = noteBlocks.calloutStyle(kind);
    const title = this.parser.parseInline(titleTokens);
    const titleHtml = title ? `<span class="md-callout-text">${title}</span>` : "";
    return (
      `<div class="md-callout md-tone-${tone}"><div class="md-callout-title">` +
      `<span class="md-callout-kind"><span aria-hidden="true">${glyph} </span>${kind.toUpperCase()}</span>${titleHtml}</div>` +
      `${this.parser.parse(tokens)}</div>\n`
    );
  },
};

// Today's date for data blocks (phases and targets mark where today falls);
// set for the duration of one markdownToHtml call.
let renderingToday = "";

function localToday() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const notesMarked = new markedLib.Marked({
  gfm: true,
  breaks: true, // a single newline is a line break, as typed
  extensions: [callout],
  renderer: {
    heading({ tokens, depth }) {
      const tag = headingTag(depth);
      const text = `<span class="md-h-text">${this.parser.parseInline(tokens)}</span>`;
      return `<${tag} class="md-h md-h${depth}">${text}</${tag}>\n`;
    },
    checkbox({ checked }) {
      const glyph = checked ? "[x]" : "[ ]";
      const state = checked ? "done: " : "to do: ";
      return (
        `<span class="md-task-mark${checked ? " done" : ""}" aria-hidden="true">${glyph}</span>` +
        `<span class="sr-only">${state}</span>`
      );
    },
    // ```schedule / ```phases / ```targets draw their data; anything else,
    // or a block that doesn't fit its format, stays a code block.
    code({ text, lang }) {
      const render = noteBlocks.renderers[(lang || "").trim().toLowerCase()];
      return (render && render(text, renderingToday)) || false;
    },
  },
});

// Unsanitized -- only for tests and for renderMarkdown below.
// `today` ("YYYY-MM-DD", default the browser's date) is where data blocks
// mark the present.
function markdownToHtml(source, today = localToday()) {
  renderingToday = today;
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
    "video", "audio", "source", "track", "picture", "image", "use", "style", "feimage",
  ],
  FORBID_ATTR: ["id", "name", "form", "formaction", "style", "srcset", "ping", "poster", "background"],
};
const RENDERER_CLASSES = new Set([
  "md-h", "md-h1", "md-h2", "md-h3", "md-h4", "md-h5", "md-h6", "md-h-text",
  "md-task-mark", "done", "sr-only", "md-callout", "md-callout-title", "md-callout-kind", "md-callout-text",
  "md-tone-flame", "md-tone-cobalt", "md-tone-moss", "md-tone-ink",
]);
const DATA_BLOCK_CLASS_PREFIX = "nb-"; // note-blocks.js's own classes
const isRendererClass = (name) => RENDERER_CLASSES.has(name) || name.startsWith(DATA_BLOCK_CLASS_PREFIX);


// This app's own paths, or embedded data -- never another site.
// Resolved the way the browser will resolve it, so tricks like "/\\host"
// or a tab inside "https:" can't reach another site.
function isLocalImageSource(src) {
  let url;
  try {
    url = new URL(src, document.baseURI);
  } catch {
    return false;
  }
  if (url.protocol === "data:") return /^data:image\//i.test(url.href);
  return url.origin === window.location.origin;
}

function renderMarkdown(source, today) {
  const fragment = globalThis.DOMPurify.sanitize(markdownToHtml(source, today), SANITIZE_OPTIONS);
  applyBarPositions(fragment);
  addSectionTaskCounts(fragment);
  return fragment;
}

// Data blocks place bar segments and markers with data-left/data-width
// (percent) since inline styles don't survive sanitizing. Clamped, so raw
// HTML using the same attributes stays inside its block.
const MAX_SCHEDULE_COLUMNS = 24;
const clamp = (value, low, high) => Math.min(Math.max(value, low), high);

function applyBarPositions(fragment) {
  const percentStyle = (value) => `${clamp(Number(value) || 0, 0, 100)}%`;
  for (const node of fragment.querySelectorAll(".nb-pos")) {
    if (node.dataset.left !== undefined) node.style.left = percentStyle(node.dataset.left);
    if (node.dataset.width !== undefined) node.style.width = percentStyle(node.dataset.width);
  }
  for (const node of fragment.querySelectorAll(".nb-schedule[data-cols]")) {
    const columns = clamp(Number(node.dataset.cols) || 1, 1, MAX_SCHEDULE_COLUMNS);
    node.style.setProperty("--nb-cols", String(columns));
  }
}

// Each heading with task items under it (up to the next heading) gets a
// "done/total" count, like a goal's progress on the stats page.
function addSectionTaskCounts(fragment) {
  let heading = null;
  let done = 0;
  let total = 0;
  const finishSection = () => {
    if (!heading || total === 0) return;
    const count = fragment.ownerDocument.createElement("span");
    count.className = done === total ? "md-h-count complete" : "md-h-count";
    count.textContent = done === total ? `✓ ${done}/${total}` : `${done}/${total}`;
    count.title = `${done} of ${total} tasks done`;
    heading.append(count);
  };
  for (const node of fragment.children) {
    if (node.classList.contains("md-h")) {
      finishSection();
      heading = node;
      done = 0;
      total = 0;
      continue;
    }
    const marks = node.querySelectorAll(".md-task-mark");
    total += marks.length;
    done += node.querySelectorAll(".md-task-mark.done").length;
  }
  finishSection();
}

function keepOnlyRendererClasses(node) {
  if (!node.hasAttribute("class")) return;
  const kept = [...node.classList].filter(isRendererClass);
  if (kept.length) node.setAttribute("class", kept.join(" "));
  else node.removeAttribute("class");
}

// Links in notes open in a new window, never replacing the app itself.
function openLinksInNewWindow(node) {
  // nodeName, lower-cased: an <a> inside inline SVG reports "a", not "A";
  // SVG links may also use the older xlink:href
  if (node.nodeName.toLowerCase() !== "a") return;
  const href = node.getAttribute("href") ?? node.getAttribute("xlink:href");
  if (href && !href.startsWith("#")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
}

// SVG paint and effects (fill="url(...)", filter, mask...) may only point
// at something in the same note ("url(#id)"), never at a file elsewhere.
const OUTSIDE_URL_REFERENCE = /url\(\s*['"]?(?!#)/i;

function dropOutsideUrlReferences(node) {
  for (const { name, value } of [...node.attributes]) {
    if (OUTSIDE_URL_REFERENCE.test(value)) node.removeAttribute(name);
  }
}

// Other SVG elements that load by link (<pattern>, gradients, <textPath>...)
// may only point inside the note. Links (<a>) are left to openLinksInNewWindow.
const LINK_ATTRIBUTES = ["href", "xlink:href"];

function dropOutsideSvgLinks(node) {
  if (node.nodeName.toLowerCase() === "a") return;
  for (const name of LINK_ATTRIBUTES) {
    const value = node.getAttribute(name);
    if (value !== null && !value.trim().startsWith("#")) node.removeAttribute(name);
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
    dropOutsideUrlReferences(node);
    dropOutsideSvgLinks(node);
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
