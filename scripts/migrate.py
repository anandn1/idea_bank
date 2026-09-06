#!/usr/bin/env python3
"""One-time (and safely re-runnable) import of ~/ideas/inbox.md into idea-bank-v2.

READ-ONLY against the old system: this script only ever opens
~/ideas/inbox.md for reading. It never writes to, moves, or deletes
anything under ~/ideas/.

Each line of inbox.md looks like:
    2026-06-29 12:07 some idea text

Lines are inserted as status='inbox' rows, preserving the original
timestamp as both created_at and updated_at.

Two known-corrupted lines from 2026-09-03 contain captured shell output
(e.g. a zsh_history grep result) rather than real ideas. Those, plus any
other line whose text is blank or looks like accidentally-captured shell
output, are NOT imported as ideas -- they're recorded in the
flagged_imports table for manual review instead.

Re-running is safe: every raw line (imported or flagged) is recorded in
import_log by exact text, so a second run only processes lines that are
new since the last run (e.g. if the old system is still capturing ideas
while both systems run in parallel).
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dbutil  # noqa: E402

OLD_INBOX = Path.home() / "ideas" / "inbox.md"

LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (.*)$")

# Heuristics for "this doesn't look like a real idea, it looks like
# captured shell output or an empty invocation".
CORRUPTION_MARKERS = ("zsh_history", "bash_history", ".zsh_history", "/home/")


def classify(text: str) -> str | None:
    """Return a flag reason if the idea text looks corrupted, else None."""
    if not text.strip():
        return "blank text (idea() invoked with no arguments)"
    for marker in CORRUPTION_MARKERS:
        if marker in text:
            return f"looks like captured shell output (contains {marker!r})"
    return None


def record_imported(conn, raw_line: str, text: str, timestamp: str) -> None:
    created_at = f"{timestamp}:00"
    conn.execute(
        "INSERT INTO ideas (text, status, created_at, updated_at) VALUES (?, 'inbox', ?, ?)",
        (dbutil.encrypt_str(text), created_at, created_at),
    )
    conn.execute(
        "INSERT INTO import_log (raw_line, action, processed_at) VALUES (?, 'imported', ?)",
        (dbutil.encrypt_str(raw_line), dbutil.now_str()),
    )


def record_flagged(conn, raw_line: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO flagged_imports (raw_line, reason, flagged_at) VALUES (?, ?, ?)",
        (dbutil.encrypt_str(raw_line), dbutil.encrypt_str(reason), dbutil.now_str()),
    )
    conn.execute(
        "INSERT INTO import_log (raw_line, action, processed_at) VALUES (?, 'flagged', ?)",
        (dbutil.encrypt_str(raw_line), dbutil.now_str()),
    )


def process_line(conn, raw_line: str) -> str:
    """Import or flag one raw line. Returns 'imported' or 'flagged'."""
    match = LINE_RE.match(raw_line)
    if not match:
        record_flagged(conn, raw_line, "does not match 'YYYY-MM-DD HH:MM text' format")
        return "flagged"

    timestamp, text = match.group(1), match.group(2)
    reason = classify(text)
    if reason:
        record_flagged(conn, raw_line, reason)
        return "flagged"

    record_imported(conn, raw_line, text, timestamp)
    return "imported"


def print_summary(counts: dict, conn) -> None:
    print("--- migration summary ---")
    print(f"imported as new inbox ideas : {counts['imported']}")
    print(f"flagged for manual review   : {counts['flagged']}")
    print(f"already migrated (skipped)  : {counts['already_done']}")

    if counts["flagged"]:
        print("\nFlagged lines (see flagged_imports table for full detail):")
        rows = conn.execute(
            "SELECT raw_line, reason FROM flagged_imports ORDER BY id"
        ).fetchall()
        for row in rows:
            raw_line = dbutil.decrypt_str(row["raw_line"])
            reason = dbutil.decrypt_str(row["reason"])
            print(f"  - {raw_line!r}\n    reason: {reason}")

    print(f"\n~/ideas/inbox.md was only read, never modified: {OLD_INBOX}")


def main():
    if not OLD_INBOX.exists():
        print(f"old inbox not found at {OLD_INBOX}, nothing to migrate")
        return

    raw_lines = OLD_INBOX.read_text().splitlines()
    counts = {"imported": 0, "flagged": 0, "already_done": 0}

    with dbutil.connection() as conn:
        already_processed = {
            dbutil.decrypt_str(row["raw_line"])
            for row in conn.execute("SELECT raw_line FROM import_log")
        }

        for raw_line in raw_lines:
            if not raw_line.strip():
                continue
            if raw_line in already_processed:
                counts["already_done"] += 1
                continue
            counts[process_line(conn, raw_line)] += 1
            already_processed.add(raw_line)

        conn.commit()
        print_summary(counts, conn)


if __name__ == "__main__":
    main()
