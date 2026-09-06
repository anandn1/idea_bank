# AGENTS.md

Architecture and ground rules for anyone — human or AI agent — working on
idea-bank-v2. For how to install/run/use the app, see `README.md`; this
file is about how the codebase is put together and what must not change
casually.

## What this is

A local, single-user idea/goal tracker: a Flask + SQLite backend, a
vanilla-JS single-page GUI, and a standalone CLI — all three talk to the
same database through one shared module, `dbutil.py`. No build step, no
frontend framework, no external network calls.

## Architecture

- **`dbutil.py`** — the only place that opens the database directly, apart
  from `scripts/*.py`. Schema, migrations, encryption, and every
  read/write operation on ideas and goals lives here. `server.py` and
  `cli/idea` both call into it; neither touches SQLite on its own.
- **`server.py`** — Flask app: thin route handlers that validate a request
  and delegate to `dbutil.py`, plus serving `static/`.
- **`cli/idea`** — argparse CLI, calling `dbutil.py` directly (no HTTP, no
  need for the server to be running). Runs on the system `python3`, not
  the venv, so it works from any terminal without activating anything —
  `dbutil.py` falls back to the venv's `site-packages` for its one
  non-stdlib dependency (`cryptography`) if it's not on the system path.
- **`static/`** — vanilla HTML/CSS/JS, no build step, no framework.
  `index.html` is the board; `idea.html` is a standalone pop-out idea
  editor, opened from the board's detail modal.
- **`scripts/`** — `migrate.py` (one-time/re-runnable import from the old
  `~/ideas/` system, strictly read-only against it) and `expire.py` (the
  queued → archive sweep, run by a systemd timer).
- **`desktop/`** — turns the GUI into a clickable app-menu entry: a
  `.desktop` file plus a launcher script that opens the board in a
  chrome-less browser window. No native-app runtime, no new dependency.

## Rules that must not be broken

1. **CLI/GUI equivalence, with two named exceptions.** Anything the GUI can
   do to an *existing* idea or goal (move, edit, complete, delete), the CLI
   can do, and vice versa — both ultimately call the same `dbutil.py`
   operations, and the JSON API mirrors the CLI's `--json` output shape.
   Two things break that symmetry on purpose, in opposite directions:
   - **Display-only GUI features have no CLI equivalent** (the theme
     toggle, the smart-default-date cutoff, the pop-out window, the desktop
     launcher) — there's no data behind them to script against.
   - **Capturing a new idea and linking a goal to an idea are CLI-only**
     (`idea "text"`, `idea goal link`/`unlink`) — the GUI has no input for
     either. This was a deliberate choice, not an oversight: the CLI (and
     any agent using it) is where new content and connections enter the
     system; the GUI is for browsing and managing what already exists. A
     goal still *shows* its linked idea in the GUI (read-only), it just
     can't be set there.
   When you add a capability to one surface, add it to the other in the
   same change *unless* it falls into one of these two named exceptions —
   don't invent a third one without updating this file.
2. **`~/ideas/` is read-only, forever.** It's the old system this one
   replaced. Nothing here may write to, move, or delete anything under
   it — `migrate.py` only ever opens `inbox.md` for reading. If you touch
   `migrate.py`, verify `md5sum ~/ideas/inbox.md` is unchanged before and
   after.
3. **Free text is encrypted at rest.** Idea text/notes/fields, goal text,
   and the raw lines `migrate.py` logs are encrypted (`dbutil.encrypt_str`
   / `decrypt_str`, Fernet) before they're written to `data/ideas.db`. The
   key lives at `~/.config/idea-bank/secret.key` — outside the repo,
   never committed, never copied alongside the database. Any new
   free-text column must be written through `encrypt_str` and read back
   through `decrypt_str` (or a `row_to_*` helper that already does), never
   read raw. Status, timestamps, and ids stay plaintext — they drive SQL
   (`WHERE`, `ORDER BY`, the status `CHECK`) and aren't personal content.
4. **Schema migrations are additive, automatic, and idempotent.** SQLite
   can't `ALTER` a `CHECK` constraint or drop a column, so a change that
   needs one rebuilds the table (rename → create with the new schema →
   copy → drop), guarded by checking the existing schema/data first — see
   `_ensure_frontier_status` for a constraint change and
   `_ensure_encrypted_content` for a data-shape change. Every migration
   runs automatically inside `get_conn()`, so every entry point (server,
   CLI, scripts) self-heals on its first connection; there's no separate
   manual migration step to remember to run.

## Conventions

- Every `dbutil.py` write function either takes an open `conn` or opens
  its own via the `connection()` context manager, and commits before
  returning — callers never manage transactions by hand.
- CLI subcommands all support `--json` and use meaningful exit codes (`0`
  success, `1` well-formed but rejected, `2` bad arguments). Treat this as
  a stable contract other tools and agents script against, not an
  incidental detail — see `.claude/skills/idea-cli/SKILL.md`.
- Comments explain *why*, not *what* — a non-obvious constraint, a
  workaround, a decision that would surprise a reader. Well-named code and
  git history carry the rest; don't restate the code in prose next to it.
- Tests never touch the real database or `~/ideas/`. Every test gets an
  isolated SQLite file and encryption key via `IDEA_BANK_DB_PATH` /
  `IDEA_BANK_KEY_PATH` (see `tests/conftest.py`) — set those two env vars
  before running the CLI or server by hand against scratch data too.

## Adding a feature: where it needs to land

A new idea/goal capability typically touches, in order: `dbutil.py`
(schema + operation) → `server.py` (route) → `cli/idea` (subcommand) →
`static/app.js` + `index.html` (GUI) → `tests/` (both the `dbutil.py`
level and full CLI-subprocess level) → `README.md`. Stopping partway
through that list is how rule 1 gets violated.

## See also

- `README.md` — installing, running, and using the app (CLI, GUI, and the
  JSON API), plus the log of assumptions made while building each feature.
- `.claude/skills/idea-cli/SKILL.md` — CLI usage reference for an agent
  operating this tool on a user's behalf.
