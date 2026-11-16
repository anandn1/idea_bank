// Small helpers shared by the board (app.js) and the full idea view
// (idea-view.js). Plain globals, loaded before either script.

const WEEKDAY_DISPLAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const THEME_STORAGE_KEY = "idea-bank-theme";

// The theme saved by the board's toggle ("dark"/"light"/"system"), or null.
function readStoredTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return null; // storage unavailable (private browsing, etc.)
  }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// "YYYY-MM-DD" as local midnight (Date's own parser would read it as UTC).
function parseLocalDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day);
}

// Monday=0..Sunday=6, matching the backend's weekday numbering.
function mondayFirstWeekday(date) {
  return (date.getDay() + 6) % 7;
}

// The server's timestamps are "YYYY-MM-DD HH:MM:SS" in local time.
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

function formatWeekdays(weekdays) {
  if (!weekdays) return "one-off";
  const days = new Set(weekdays);
  if (days.size === 7) return "daily";
  if (days.size === 5 && [0, 1, 2, 3, 4].every((d) => days.has(d))) return "weekdays";
  if (days.size === 2 && days.has(5) && days.has(6)) return "weekends";
  return [...days].sort((a, b) => a - b).map((d) => WEEKDAY_DISPLAY[d]).join("/");
}

// A completion rate (0..1, or null when nothing was due) as "79%" / "--".
function formatPercent(rate) {
  return rate === null ? "--" : `${Math.round(rate * 100)}%`;
}
