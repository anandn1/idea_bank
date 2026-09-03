# idea-bank-v2

A local, keyboard-first replacement for the old `~/ideas/` capture system:
Python (Flask) + SQLite backend, single-page HTML/CSS/JS GUI, all served on
`localhost` only. No sign-in, no external network calls.

The old system under `~/ideas/` (inbox.md, expire.sh, active/queued/archive/horizon,
idea-triage.timer, idea-horizon-review.timer) is **untouched** — see
[Confirmation: ~/ideas/ was left alone](#confirmation-ideas-was-left-alone) below,
including one accidental write during development that's disclosed there.

## Running it

```
cd ~/idea_bank
./install.sh
```

This creates a venv, installs Flask, symlinks `cli/idea` to `~/.local/bin/idea`,
installs the new systemd user units (`idea-bank-v2-*`, separate names from the
old `idea-triage`/`idea-horizon-review` units, which are left alone), and starts
the server as a persistent user service.

Open **http://127.0.0.1:8420/** — or just run `idea-bank-v2-triage.timer` once,
which opens it for you.

To run the server by hand instead of via systemd:

```
.venv/bin/python server.py
```

## Testing

```
.venv/bin/pip install -r requirements-dev.txt   # adds pytest to the venv
.venv/bin/pytest
```

Covers `dbutil.py`, `cli/idea` (both its pure helpers directly and full
subprocess invocations asserting on `--json` output and exit codes -- the
same contract a human or an agent sees), `scripts/expire.py`, and
`scripts/migrate.py`. Every test runs against an isolated temp SQLite file
(never `data/ideas.db`) via the `IDEA_BANK_DB_PATH` env var dbutil.py reads
when set; `migrate.py`'s tests additionally point `OLD_INBOX` at a throwaway
file, so the suite can never write to or read the real `~/ideas/inbox.md`.
Not covered yet: `server.py` (the Flask API) and the GUI itself -- those
were verified manually (curl / Playwright) during development but have no
automated tests.

## How it works end to end

**Capture / query CLI** — `idea` (`cli/idea`, symlinked onto `PATH`) opens
`data/ideas.db` directly with Python's `sqlite3` module; it does not need the
Flask server running. Run `idea --help` (or `idea <command> --help`) for full
usage. It's built for both a human at a keyboard and an AI agent scripting
against it: every subcommand accepts `--json` for machine-readable output,
and exit codes are meaningful (`0` success, `1` valid request but the target
idea didn't exist / was rejected, `2` bad arguments).

```
idea "ship the migration"          # capture -> inbox (bare text = capture)
idea -q "revisit nvim config"      # capture straight -> queued
idea -a / -H / -x                  # ...active / horizon / archive
idea --status queued "text"        # long form of the same flags

idea list                          # all ideas, newest-updated first
idea list -q                       # only queued
idea list --json                   # machine-readable, for scripting/agents

idea show 12                       # full detail for one idea
idea move 12 active --json         # change status, print the updated idea as JSON
idea edit 12 "new text"            # rewrite text (single idea only)
idea delete 12                     # delete

# batch: show / move / delete all take multiple ids
idea move 12 13 14 active          # move several ideas to active in one call
idea delete 12 13 14               # delete several ideas in one call
idea show 12 13 14 --json          # -> JSON array when more than one id is given

# batch capture: one idea per non-empty line of stdin
printf "idea one\nidea two\n" | idea capture --stdin -q
```

If any id in a batch `move`/`delete`/`show` doesn't exist, the whole call
fails (nothing is changed) and reports which id(s) were missing -- so a
partial id list never leaves things half-moved.

Note: `-h` is reserved for `--help` (argparse's default), which is why the
horizon shortcut is uppercase `-H` — everywhere else in this project
(the GUI, this README) horizon is lowercase `h`.

**Structured fields** — every idea can carry arbitrary `key=value` metadata
(due dates, priority, owner, a URL, whatever) on top of its text. There's no
fixed schema: nothing is required, an idea with no fields is indistinguishable
from before, and the vocabulary of keys is entirely up to you.

```
idea "book a room" --field due=2026-10-01 --field priority=high
idea edit 12 --field owner=me          # add/overwrite a field, text unchanged
idea edit 12 --unset-field owner       # remove a field
idea show 12                           # prints fields if the idea has any
idea list                              # a leading `*` marks ideas that have fields
```

Stored as a JSON object in a `fields` column (`NULL`/`{}` when unused). The
JSON API accepts/returns the same shape: `POST`/`PATCH .../api/ideas` take an
optional `"fields": {...}` object (PATCH replaces the whole object when
given), and every idea in `GET /api/ideas` includes `"fields"`.

**GUI** — `server.py` serves `static/index.html` and a small JSON API
(`GET/POST /api/ideas`, `PATCH/DELETE /api/ideas/<id>`) backed by the same
SQLite file. `static/app.js` renders five columns (Inbox, Active, Queued,
Horizon, Archive) and covers the same ground as the CLI, keyboard-first:

- Typing anywhere outside the capture box is a shortcut; the capture input
  itself is auto-focused on load and via `/`.
- **Capture-to-status**: pills next to the capture input (click, or
  Alt+I/A/Q/H/X while the input is focused) choose where the next capture
  goes; it resets to Inbox after each capture, matching the CLI's per-call
  default.
- `j` / `k` or `↓` / `↑` move the focus between idea cards (flattened across
  all five columns, left to right).
- `a` / `q` / `h` / `x` move the focused (or selected, see below) card(s).
  A single card slides into its new column — the one deliberate motion in
  the UI, skipped automatically under `prefers-reduced-motion`; moving more
  than one at once re-renders directly instead, since several simultaneous
  slides across columns read as noise, not signal.
- `e` edits the focused card's text in place (Enter saves, Escape cancels,
  clicking away saves) — the GUI equivalent of `idea edit`.
- `d` (or Delete/Backspace) deletes the selected card(s), after a confirm
  prompt — the GUI equivalent of `idea delete`. Cannot be undone.
- `v` toggles range-select ("visual mode", vim-style): `j`/`k` extend the
  range from wherever `v` was pressed, a status bar shows the count, and
  `a`/`q`/`h`/`x`/`d` then apply to every selected card at once — the GUI
  equivalent of the CLI's batch `move`/`delete`. `Escape` cancels back to a
  single selection.
- **Enter** (or double-click, or drag) opens the focused card's **detail
  view** — a modal with the full text (editable), status (as pills), every
  structured field (editable, with an "add field" row), freeform notes, and
  a delete button. Typing in the modal never triggers board shortcuts.
  Closing it (the `×`, "done", or clicking the backdrop) saves everything
  at once; **Escape discards** instead, matching the inline `e` edit's
  convention. This is the GUI's full equivalent of `idea show` + `idea edit
  --field` + `idea edit --unset-field` combined.
- **Drag and drop**: drag a card onto another column to move it there (same
  effect as `a`/`q`/`h`/`x`, mouse-driven). Single-card only — for moving
  several at once, use `v` + `j`/`k` + a status key instead.
- Clicking a card selects it (mouse fallback); Shift+click extends a range
  the same way `v` + `j`/`k` does. Clicking is never required.

**Expiry** — `scripts/expire.py` is the server-side replacement for the old
`expire.sh`. It finds every idea with `status='queued'` whose `updated_at` is
more than 8 weeks old and flips it to `status='archive'`, logging each move to
stdout and to `data/expire.log`. It's run weekly by
`idea-bank-v2-triage.service`, which then opens the GUI in your default
browser via `xdg-open`.

**Quarterly review** — `idea-bank-v2-horizon-review.timer` fires quarterly and
opens `http://127.0.0.1:8420/#horizon`, which scrolls the Horizon column into
view; if `xdg-open` isn't available it falls back to `notify-send`.

## Migration

`scripts/migrate.py` reads `~/ideas/inbox.md` **read-only** — it never writes
to, moves, or deletes anything under `~/ideas/`. Each line
(`YYYY-MM-DD HH:MM text`) becomes a `status='inbox'` row, with the original
timestamp preserved as both `created_at` and `updated_at`.

Two lines dated 2026-09-03 were known to contain captured shell output rather
than real ideas. The script doesn't rely on knowing that in advance — it flags
(instead of imports) any line whose text is blank, or that contains a
shell-history/path marker (`zsh_history`, `bash_history`, `/home/`), into a
`flagged_imports` table for manual review, along with any line that doesn't
even match the `date time text` shape. Nothing flagged is silently dropped —
you can inspect the full list at any time:

```
.venv/bin/python -c "
import dbutil
with dbutil.connection() as conn:
    for row in conn.execute('SELECT * FROM flagged_imports'):
        print(dict(row))
"
```

**Re-running it is safe.** Every raw line — imported or flagged — is recorded
by its exact text in an `import_log` table. Running `migrate.py` again only
processes lines that are new since the last run (useful since the old system
keeps capturing to `inbox.md` until you retire it):

```
.venv/bin/python scripts/migrate.py
```

Result of the run performed while building this: **7 imported**, **2 flagged**
(the blank capture and the shell-output line), matching the known data issue
exactly.

## Confirmation: ~/ideas/ was left alone

`expire.sh`, the `active/queued/archive/horizon` directories, and the old
`idea-triage.timer` / `idea-horizon-review.timer` systemd units were never
written to, moved, enabled, disabled, or deleted by anything in this project.
`migrate.py` only ever opens `inbox.md` for reading.

**One disclosed exception:** while testing the new `idea` CLI during
development, two commands were run before a PATH/shell-function conflict (see
below) was fixed, and — because the old `idea()` zsh function was still
shadowing the new one at that moment — those two test commands appended two
lines to `~/ideas/inbox.md` instead of hitting the new database as intended:

```
2026-09-03 09:32 test capture via new CLI
2026-09-03 09:32 capture while server is stopped
```

Those lines are harmless (equivalent in spirit to the other test-artifact
lines already in the file) and are still sitting in `inbox.md` — they were
**not** removed, since editing that file, even to undo a mistake, is itself a
write to `~/ideas/`, and this project treats that file as strictly read-only
going forward. They were also not imported as real ideas into the new
database (the two corresponding rows were deleted from `ideas` after the
migration ran). Delete them from `inbox.md` yourself if you'd like, whenever
you're ready to touch that file.

## Assumptions made while building this

- **`idea()` shell function vs. new `idea` CLI.** In zsh, a shell function
  named `idea` shadows an executable named `idea` on `PATH`, so simply
  symlinking the new CLI wasn't enough for `idea "text"` to reach the new
  database. Per your choice, the old `idea() { ... }` function in `~/.zshrc`
  was **commented out** (not deleted) with a note on how to restore it. This
  is the one change outside `~/idea_bank/` and `~/ideas/` made by this
  project. `~/ideas/inbox.md` and everything else about the old system is
  unaffected — if you uncomment the function again, it will resume appending
  to `inbox.md` exactly as before. The other old shell functions
  (`idea-queue`, `horizon`) were left untouched since they don't collide with
  anything new.
- **A persistent server unit.** The brief asked for triage/horizon-review
  timers that open the GUI, but not for a systemd unit that keeps the server
  itself running. Since opening a browser tab to `localhost:8420` is only
  useful if something is listening there, `install.sh` also installs and
  enables `idea-bank-v2-server.service` (`Type=simple`, restarts on failure,
  starts at login).
- **Port 8420.** Chosen arbitrarily to avoid clashing with common local dev
  ports (3000, 5000, 8000, 8080).
- **Timestamp format.** Stored as `YYYY-MM-DD HH:MM:SS` (local time, ISO-ish,
  sortable as text). Migrated rows get `:00` appended to the old system's
  minute-precision timestamps.
- **Flattened keyboard navigation.** `j`/`k`/arrows move through all cards in
  column order (Inbox → Active → Queued → Horizon → Archive), not just within
  one column, since the brief didn't specify and this keeps a single mental
  model for "next/previous idea."
- **Corruption heuristics for migration** are pattern-based (blank text,
  shell-history/path markers) rather than hardcoded to the two known bad
  lines, so the script stays useful if `inbox.md` grows more such lines
  before you retire the old system.

## Project layout

Lives at `~/idea_bank/` (the project's name -- "idea-bank-v2", as in the
successor to the old `~/ideas/` system -- is separate from its directory
name):

```
idea_bank/
  server.py            Flask app: JSON API + serves static/
  dbutil.py            shared SQLite schema/connection helper
  static/
    index.html
    style.css
    app.js
  cli/idea              standalone capture script
  scripts/
    expire.py            8-week queued -> archive sweep
    migrate.py            one-time/re-runnable import from ~/ideas/inbox.md
  systemd/
    idea-bank-v2-server.service
    idea-bank-v2-triage.service / .timer
    idea-bank-v2-horizon-review.service / .timer
  install.sh
  requirements.txt
  data/                 ideas.db, expire.log (created at runtime)
```
