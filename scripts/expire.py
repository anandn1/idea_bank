#!/usr/bin/env python3
"""Move queued ideas older than 8 weeks (by updated_at) to archive.

Server-side replacement for the old ~/ideas/expire.sh. Run by the
idea-bank-v2-triage systemd service (weekly). Logs each expiry action
to stdout (captured by the systemd journal) and to data/expire.log.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dbutil  # noqa: E402

EIGHT_WEEKS = timedelta(weeks=8)
LOG_PATH = PROJECT_ROOT / "data" / "expire.log"


def log(message: str) -> None:
    print(message)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(f"{dbutil.now_str()} {message}\n")


def expire_if_stale(conn, row, cutoff: datetime) -> bool:
    try:
        updated_at = datetime.fromisoformat(row["updated_at"])
    except ValueError:
        return False
    if updated_at >= cutoff:
        return False

    conn.execute(
        "UPDATE ideas SET status = 'archive', updated_at = ? WHERE id = ?",
        (dbutil.now_str(), row["id"]),
    )
    log(
        f"expired idea #{row['id']} (queued since {row['updated_at']}): {row['text']!r}"
    )
    return True


def main():
    cutoff = datetime.now() - EIGHT_WEEKS
    with dbutil.connection() as conn:
        rows = conn.execute(
            "SELECT id, text, updated_at FROM ideas WHERE status = 'queued'"
        ).fetchall()

        expired = sum(expire_if_stale(conn, row, cutoff) for row in rows)
        conn.commit()

        if expired == 0:
            log("no ideas expired")


if __name__ == "__main__":
    main()
