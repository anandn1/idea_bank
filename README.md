# Idea Bank

A local-first, keyboard-centric productivity system for tracking ideas and daily goals. Built with a Python (Flask) + SQLite backend and a clean, responsive single-page web interface styled with a focused terminal aesthetic.

Runs entirely on `localhost` with zero external network requests, no user accounts or analytics, and client-side encryption for personal data at rest.

---

## Features

- **Dual Interfaces**: Work seamlessly from both a full-featured CLI (`idea`) and a web GUI (`localhost:8420`), both interacting with the same local SQLite database.
- **Goals & Streak Tracking**: Track one-off milestones and recurring daily/weekly habits with streak statistics and completion archives.
- **Structured Idea Lifecycle**: Organize thoughts into distinct stages:
  `inbox` &rarr; `active` &rarr; `queued` &rarr; `horizon` &rarr; `frontier` &rarr; `archive`.
- **Encrypted at Rest**: All idea text, field notes, and goal contents are encrypted using Fernet (AES-128-CBC + HMAC-SHA256). The encryption key is kept securely on your local system (`~/.config/idea-bank/secret.key`).
- **Keyboard-Driven & Responsive**: Fast keyboard shortcuts (`j`/`k`, `/`, status toggles), interactive drag-and-drop organization, and detachable pop-out editor windows.
- **Automation & Scripting Ready**: Subcommands support `--json` output and standardized exit codes for easy scripting and tooling integrations.

---

## Installation & Setup

### Prerequisites

- Python 3.10 or higher
- Linux desktop (optional: enables background systemd services and desktop application shortcut)

### Quick Start

Clone the repository and run the setup script:

```bash
git clone https://github.com/anandn1/idea_bank.git
cd idea_bank
./install.sh
```

The installer will:
1. Create a local Python virtual environment (`.venv/`) and install dependencies.
2. Symlink `cli/idea` into `~/.local/bin/idea` (ensure `~/.local/bin` is in your `$PATH`).
3. Set up and start the background user service (`idea-bank-v2-server.service`).
4. Add the desktop application launcher (`idea-bank.desktop`).

Open **http://127.0.0.1:8420** in your browser, or launch **Idea Bank** from your application menu.

### Running Manually

If you prefer to start the server directly without systemd:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

---

## Command Line Usage

The `idea` CLI tool interacts directly with the local SQLite database and works independently of whether the web server is running.

### Capturing Ideas

```bash
idea "Refactor auth middleware"           # Capture to inbox (default)
idea -q "Read research paper"             # Capture straight to queued
idea -a "Build prototype"                 # Capture to active
idea -H "Start podcast"                   # Capture to horizon (long-term)
idea -f "Moonshot project"                # Capture to frontier
```

Batch capture from standard input:
```bash
printf "Task 1\nTask 2\nTask 3\n" | idea capture --stdin -q
```

### Managing Ideas

```bash
idea list                                # List all ideas (newest first)
idea list -q                             # List only queued ideas
idea list --json                         # Format output as JSON

idea show 42                             # Inspect idea #42
idea edit 42 "Updated description"       # Update text
idea move 42 active                      # Change status
idea move 10 11 12 queued                # Batch move multiple items
idea delete 42                           # Delete an item
```

### Custom Metadata & Notes

Attach custom `key=value` attributes and timestamped notes to any idea:
```bash
idea 12 set priority=high due=2026-11-05 owner=alice
idea 12 rm due
idea 12 note "Follow up after morning standup"
```

### Goals & Daily Habits

```bash
idea goal list                           # View current active goals
idea goal "Complete documentation" --date 2026-11-02   # One-off goal
idea goal "Morning run" --weekdays mon,wed,fri         # Recurring habit
idea goal done 1                         # Mark goal #1 complete for today
idea goal undo 1                         # Uncheck goal #1
idea goal stop 2                         # Stop recurring goal #2
idea goal history                        # View past completed goals
idea goal stats                          # Completion rates, per-goal streaks, heatmap
idea goal link 1 42                      # Link goal #1 to idea #42
idea goal unlink 1 42                    # Remove link between goal #1 and idea #42
```

---

## Web Interface

- **Goals View**: Real-time habit streaks, daily checklists, goal creation, and collapsible history sections.
- **Stats View**: A year-long completion heatmap, 7/30/90-day and all-time completion rates, a by-weekday breakdown, each recurring goal's rate and streaks, and one-off goals done/missed/pending.
- **Kanban Board**: Drag-and-drop cards across stages, instant search and status filtering, and multi-card actions.
- **Card Details & Pop-out**: Edit metadata attributes, view linked goals, or pop out a card into an independent window (`static/idea.html`).
- **Clean Aesthetic**: Distraction-free typography powered by self-hosted JetBrains Mono font weights, with Dark, Light, and System themes.

---

## Testing

Run the test suite with `pytest`:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Tests run in isolated environments using temporary databases and ephemeral encryption keys (see `tests/conftest.py`), ensuring your local database remains untouched.

---

## Architecture & Security

- **Encrypted Content**: Idea text, notes, and goals are encrypted using Fernet prior to database storage. Identifiers, statuses, and timestamps remain unencrypted to support fast indexing, filtering, and foreign key constraints.
- **Zero External Calls**: Fully self-contained. Static assets are bundled locally, ensuring no network traffic or analytics requests are ever made.
- **Unified Logic**: Both the web GUI and the CLI operate through the same shared database layer (`dbutil.py`).

---

## License

MIT License. See [LICENSE](LICENSE) for details.
