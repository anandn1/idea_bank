"""Shared helpers for the browser tests (test_gui_*.py): talking to the
throwaway test server's JSON API to set up data and read results back.
The server, browser and page fixtures themselves live in conftest.py."""

import json
import sqlite3
import urllib.request

API_TIMEOUT_S = 10  # fail fast if the test server ever stops answering


def api(base_url: str, method: str, path: str, payload: dict | None = None):
    request = urllib.request.Request(
        base_url + path,
        data=None if payload is None else json.dumps(payload).encode(),
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=API_TIMEOUT_S) as response:
        body = response.read()
        return json.loads(body) if body else None


def make_idea(base_url: str, text: str, notes: str | None = None, **changes) -> dict:
    """Create an idea, then apply notes/status/fields if given."""
    idea = api(base_url, "POST", "/api/ideas", {"text": text})
    updates = {**changes, **({"notes": notes} if notes is not None else {})}
    if updates:
        idea = api(base_url, "PATCH", f"/api/ideas/{idea['id']}", updates)
    return idea


def make_goal(base_url: str, text: str, idea_id: int, **options) -> dict:
    """Create a goal linked to one idea; options are weekdays/target_date."""
    return api(
        base_url, "POST", "/api/goals", {"text": text, "idea_ids": [idea_id], **options}
    )


def get_idea(base_url: str, idea_id: int) -> dict:
    return api(base_url, "GET", f"/api/ideas/{idea_id}")


def get_overview(base_url: str, idea_id: int) -> dict:
    return api(base_url, "GET", f"/api/ideas/{idea_id}/overview")


def run_sql(db_path, sql: str, params: tuple = ()) -> None:
    """Write straight to the test server's database. Only for columns that
    hold no encrypted text (dates, ids) -- see dbutil.encrypt_str."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
