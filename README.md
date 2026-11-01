# Idea Bank

A local-first, keyboard-centric productivity system for tracking ideas and daily goals. Built with Python (Flask) + SQLite on the backend, paired with a vanilla HTML/CSS/JS frontend styled with a minimal terminal aesthetic.

Runs completely on `localhost` with zero external network requests, no accounts, and client-side encrypted storage at rest.

---

## Highlights

- **Dual-surface operation**: A powerful CLI (`idea`) and an uncluttered single-page web GUI (`localhost:8420`) that share the exact same SQLite database.
- **Goals & Streaks**: Track one-off and recurring daily/weekly goals with automatic streak calculations and completion archives.
- **Idea Lifecycle Management**: Six distinct stages (`inbox` &rarr; `active` &rarr; `queued` &rarr; `horizon` &rarr; `frontier` &rarr; `archive`).
- **Encrypted at Rest**: All idea text, field notes, and goal contents are encrypted using Fernet (AES-128-CBC + HMAC-SHA256) via Python's `cryptography` library. The secret key is stored locally outside the repository at `~/.config/idea-bank/secret.key`.
- **Keyboard-first & Fast**: Full keyboard navigation (`j`/`k`, `/`, shortcut keys), instant client-side filtering, drag-and-drop board organization, and standalone pop-out windows.
- **Scriptable & Agent-ready**: Every CLI command supports `--json` for automation and agent tooling.

---

## Installation & Setup

### Prerequisites
- Python 3.10+ (with SQLite support)
- Linux desktop (optional, for systemd services and desktop application shortcut)

### Quick Start

Clone the repository and run the setup script:

```bash
git clone https://github.com/anandn1/idea_bank.git
cd idea_bank
./install.sh
```

`install.sh` performs the following automatically:
1. Creates a Python virtual environment (`.venv/`) and installs dependencies.
2. Symlinks `cli/idea` into `~/.local/bin/idea` (make sure `~/.local/bin` is in your `$PATH`).
3. Installs and starts the systemd user service (`idea-bank-v2-server.service`).
4. Installs the desktop application shortcut (`idea-bank.desktop`).

Open **http://127.0.0.1:8420** in your browser, or launch **Idea Bank** from your application menu.

### Manual Server Launch

To run the Flask backend manually without systemd:

```bash
# Set up venv and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Start the server on port 8420
.venv/bin/python server.py
```

---

## Command Line Interface (CLI)

The CLI executable `cli/idea` operates directly on the SQLite database without requiring the web server to be running.

### Capturing Ideas

```bash
idea "Refactor auth middleware"           # Capture to inbox (default)
idea -q "Read paper on GRPO"              # Capture straight to queued
idea -a "Build prototype"                 # Capture to active
idea -H "Start tech podcast"              # Capture to horizon (long-term)
idea -f "Colonize Mars"                   # Capture to frontier (moonshots)
```

Batch capture from standard input:
```bash
printf "Task 1\nTask 2\nTask 3\n" | idea capture --stdin -q
```

### Managing Ideas

```bash
idea list                                # List all ideas
idea list -q                             # List only queued ideas
idea list --json                         # Output ideas as JSON

idea show 42                             # Inspect idea #42
idea edit 42 "Updated description"       # Edit text
idea move 42 active                      # Move to active
idea move 10 11 12 queued                # Batch move multiple ideas
idea delete 42                           # Delete an idea
```

### Structured Fields & Notes

Ideas support arbitrary `key=value` metadata fields:
```bash
idea 12 set priority=high due=2026-11-05 owner=alice
idea 12 rm due
idea 12 note "Follow up after morning standup"
```

### Goals & Daily Tracking

```bash
idea goal list                           # List current active goals
idea goal "Ship v2 release" --date 2026-11-02       # One-off goal
idea goal "Morning run" --weekdays mon,wed,fri      # Recurring goal
idea goal done 1                         # Mark goal #1 done for today
idea goal undo 1                         # Unmark goal #1
idea goal stop 2                         # Stop recurring goal #2
idea goal history                        # View completed goal archive
idea goal link 1 42                      # Link goal #1 to idea #42
idea goal unlink 1 42                    # Unlink goal #1 from idea #42
```

---

## Web Interface

- **Goals Dashboard**: See today's streak, check off daily recurring and one-off targets, add new goals, and collapse active/completed sections.
- **Kanban Board**: Drag-and-drop ideas across six status columns, batch move or delete cards, and filter cards instantly.
- **Detail Modal & Pop-out**: Edit text, assign key-value fields, view linked goals, or click **pop out** to open the card in an isolated floating editor window (`static/idea.html`).
- **Zero-Distraction Aesthetic**: High-contrast, monospace terminal styling utilizing self-hosted JetBrains Mono font weights with light/dark/system themes.

---

## Development & Testing

Run tests with `pytest`:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Tests run in complete isolation with mocked databases and throwaway encryption keys (see `tests/conftest.py`), ensuring your local `data/ideas.db` is never modified during test runs.

---

## Architecture & Security

- **Encryption at rest**: Content fields (`text`, `notes`, `fields`) are encrypted using Fernet before being written to SQLite. Status flags, IDs, and timestamps remain unencrypted to support fast index queries and constraints.
- **No external network calls**: The web interface uses self-hosted assets under `static/fonts/` and zero CDNs or telemetry.
- **CLI/GUI Parity**: Every action available in the GUI is fully supported in the CLI.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
