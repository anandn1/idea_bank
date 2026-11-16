"""Request validation in server.py's JSON API, via Flask's test client
against an isolated DB (the db_path fixture in conftest.py)."""

import sqlite3

import pytest

import server


@pytest.fixture
def client(db_path):
    return server.app.test_client()


@pytest.fixture
def idea_id(client):
    return client.post("/api/ideas", json={"text": "an idea"}).get_json()["id"]


@pytest.mark.parametrize("bad_text", [123, ["x"], {"a": 1}, True, "", "   ", None])
def test_create_idea_rejects_text_that_isnt_a_nonblank_string(client, bad_text):
    response = client.post("/api/ideas", json={"text": bad_text})

    assert response.status_code == 400
    assert response.get_json() == {"error": "text is required"}


@pytest.mark.parametrize("bad_text", [123, ["x"], "  "])
def test_create_goal_rejects_text_that_isnt_a_nonblank_string(client, bad_text):
    response = client.post("/api/goals", json={"text": bad_text})

    assert response.status_code == 400
    assert response.get_json() == {"error": "text is required"}


def test_create_idea_strips_its_text(client):
    response = client.post("/api/ideas", json={"text": "  padded  "})

    assert response.status_code == 201
    assert response.get_json()["text"] == "padded"


@pytest.mark.parametrize("key", ["text", "notes"])
@pytest.mark.parametrize("bad_value", [123, ["x"], {"a": 1}, False])
def test_update_idea_rejects_non_string_text_and_notes(client, idea_id, key, bad_value):
    response = client.patch(f"/api/ideas/{idea_id}", json={key: bad_value})

    assert response.status_code == 400
    assert response.get_json() == {"error": f"{key} must be a string"}
    unchanged = client.get(f"/api/ideas/{idea_id}").get_json()
    assert (unchanged["text"], unchanged["notes"]) == ("an idea", None)


def test_update_idea_still_clears_notes_with_null(client, idea_id):
    client.patch(f"/api/ideas/{idea_id}", json={"notes": "something"})

    response = client.patch(f"/api/ideas/{idea_id}", json={"notes": None})

    assert response.status_code == 200
    assert response.get_json()["notes"] is None


def test_overview_route_returns_the_overview(client, idea_id):
    response = client.get(f"/api/ideas/{idea_id}/overview")

    assert response.status_code == 200
    assert response.get_json()["idea"]["id"] == idea_id


def test_overview_route_404s_for_a_missing_idea(client):
    response = client.get("/api/ideas/999/overview")

    assert response.status_code == 404
    assert response.get_json() == {"error": "not found"}


def test_delete_route_removes_status_history(client, idea_id, db_path):
    client.patch(f"/api/ideas/{idea_id}", json={"status": "active"})

    assert client.delete(f"/api/ideas/{idea_id}").status_code == 204

    conn = sqlite3.connect(db_path)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM idea_events WHERE idea_id = ?", (idea_id,)
    ).fetchone()[0]
    conn.close()
    assert remaining == 0


def test_update_idea_strips_its_text(client, idea_id):
    response = client.patch(f"/api/ideas/{idea_id}", json={"text": "  renamed  "})

    assert response.get_json()["text"] == "renamed"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_update_idea_rejects_blank_text(client, idea_id, blank):
    response = client.patch(f"/api/ideas/{idea_id}", json={"text": blank})

    assert response.status_code == 400
    assert response.get_json() == {"error": "text cannot be empty"}


def test_update_idea_with_nothing_to_change_is_rejected(client, idea_id):
    response = client.patch(f"/api/ideas/{idea_id}", json={})

    assert response.status_code == 400
    assert response.get_json() == {"error": "no updatable fields provided"}


def test_update_missing_idea_404s(client):
    assert client.patch("/api/ideas/999", json={"text": "x"}).status_code == 404


BAD_DATES = ["not-a-date", 123, "2026-13-01", "2026-9-10", "20260910", "", 0, False, []]


@pytest.mark.parametrize("bad_date", BAD_DATES)
def test_create_goal_rejects_a_bad_target_date(client, idea_id, bad_date):
    response = client.post(
        "/api/goals", json={"text": "g", "idea_ids": [idea_id], "target_date": bad_date}
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "target_date must be YYYY-MM-DD"}
    assert client.get(f"/api/ideas/{idea_id}/overview").get_json()["goals"] == []


@pytest.mark.parametrize("bad_date", BAD_DATES)
def test_goal_check_off_rejects_a_bad_date(client, bad_date):
    goal = client.post("/api/goals", json={"text": "g"}).get_json()

    response = client.patch(
        f"/api/goals/{goal['id']}", json={"completed": True, "date": bad_date}
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "date must be YYYY-MM-DD"}


def test_goal_list_rejects_a_bad_date(client):
    response = client.get("/api/goals?date=garbage")

    assert response.status_code == 400
    assert response.get_json() == {"error": "date must be YYYY-MM-DD"}


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/api/ideas"),
        ("patch", "/api/ideas/1"),
        ("post", "/api/goals"),
        ("patch", "/api/goals/1"),
        ("post", "/api/goals/1/link"),
        ("post", "/api/goals/1/unlink"),
    ],
)
@pytest.mark.parametrize("body", [[1], "text", 5])
def test_non_object_json_bodies_are_rejected(client, idea_id, method, path, body):
    response = getattr(client, method)(path, json=body)

    assert response.status_code == 400
    assert response.get_json() == {"error": "request body must be a JSON object"}


@pytest.mark.parametrize("not_a_bool", ["false", "true", 1, 0, None])
def test_goal_check_off_needs_a_real_boolean(client, not_a_bool):
    goal = client.post("/api/goals", json={"text": "g"}).get_json()

    response = client.patch(f"/api/goals/{goal['id']}", json={"completed": not_a_bool})

    assert response.status_code == 400
    assert response.get_json() == {"error": "completed (bool) is required"}
    goals = client.get("/api/goals").get_json()["goals"]
    assert goals[0]["completed_at"] is None


def test_goal_check_off_with_no_date_means_today(client, fixed_today):
    goal = client.post("/api/goals", json={"text": "g"}).get_json()

    response = client.patch(
        f"/api/goals/{goal['id']}", json={"completed": True, "date": None}
    )

    assert response.status_code == 200
    assert client.get(f"/api/goals?date={fixed_today}").get_json()["goals"][0][
        "completed_at"
    ]


def test_goal_list_empty_date_means_today(client, fixed_today):
    response = client.get("/api/goals?date=")

    assert response.get_json()["date"] == fixed_today


# ---- field/status/link validation ----


@pytest.mark.parametrize("bad_idea_ids", [["x"], "1", [True], 1, [1.5]])
def test_create_goal_rejects_bad_idea_ids(client, bad_idea_ids):
    response = client.post("/api/goals", json={"text": "g", "idea_ids": bad_idea_ids})

    assert response.status_code == 400
    assert response.get_json() == {"error": "idea_ids must be a list of integers"}


def test_create_goal_404s_for_an_unknown_idea_id(client):
    response = client.post("/api/goals", json={"text": "g", "idea_ids": [999]})

    assert response.status_code == 404
    assert response.get_json() == {"error": "no idea with that id"}


@pytest.mark.parametrize("bad_weekdays", [["x"], [7], [-1], [True], "0,1"])
def test_create_goal_rejects_bad_weekdays(client, bad_weekdays):
    response = client.post("/api/goals", json={"text": "g", "weekdays": bad_weekdays})

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "weekdays must be a list of integers 0-6 (Mon=0..Sun=6)"
    }


def test_create_goal_rejects_weekdays_with_a_target_date(client):
    response = client.post(
        "/api/goals", json={"text": "g", "weekdays": [0], "target_date": "2030-01-01"}
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "target_date doesn't apply to a goal with weekdays"
    }


@pytest.mark.parametrize("bad_fields", [["x"], "y", 5])
def test_create_idea_rejects_non_object_fields(client, bad_fields):
    response = client.post("/api/ideas", json={"text": "t", "fields": bad_fields})

    assert response.status_code == 400
    assert response.get_json() == {"error": "fields must be an object"}


@pytest.mark.parametrize("bad_fields", [["x"], "y", 5])
def test_update_idea_rejects_non_object_fields(client, idea_id, bad_fields):
    response = client.patch(f"/api/ideas/{idea_id}", json={"fields": bad_fields})

    assert response.status_code == 400
    assert response.get_json() == {"error": "fields must be an object"}


@pytest.mark.parametrize("bad_status", ["bogus", "", 123, None])
def test_create_idea_rejects_an_invalid_status(client, bad_status):
    response = client.post("/api/ideas", json={"text": "t", "status": bad_status})

    assert response.status_code == 400
    assert response.get_json() == {"error": f"invalid status: {bad_status}"}


def test_update_idea_rejects_an_invalid_status(client, idea_id):
    response = client.patch(f"/api/ideas/{idea_id}", json={"status": "bogus"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid status: bogus"}


@pytest.mark.parametrize("route", ["link", "unlink"])
@pytest.mark.parametrize("bad_idea_id", ["1", None, True, 1.5])
def test_link_and_unlink_require_an_integer_idea_id(client, route, bad_idea_id):
    goal = client.post("/api/goals", json={"text": "g"}).get_json()

    response = client.post(
        f"/api/goals/{goal['id']}/{route}", json={"idea_id": bad_idea_id}
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "idea_id (integer) is required"}


def test_link_goal_404s_for_an_unknown_goal(client, idea_id):
    response = client.post("/api/goals/999/link", json={"idea_id": idea_id})

    assert response.status_code == 404
    assert response.get_json() == {"error": "no goal or idea with that id"}


def test_link_goal_404s_for_an_unknown_idea(client):
    goal = client.post("/api/goals", json={"text": "g"}).get_json()

    response = client.post(f"/api/goals/{goal['id']}/link", json={"idea_id": 999})

    assert response.status_code == 404
    assert response.get_json() == {"error": "no goal or idea with that id"}


def test_unlink_goal_404s_for_an_unknown_goal(client):
    response = client.post("/api/goals/999/unlink", json={"idea_id": 1})

    assert response.status_code == 404
    assert response.get_json() == {"error": "no goal with that id"}


def test_stop_goal_404s_are_really_a_400_for_a_one_off_goal(client):
    goal = client.post(
        "/api/goals", json={"text": "g"}
    ).get_json()  # one-off, no weekdays

    response = client.post(f"/api/goals/{goal['id']}/stop")

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "no weekday schedule to stop, or already stopped"
    }


def test_stop_goal_succeeds_for_a_recurring_goal(client):
    goal = client.post("/api/goals", json={"text": "g", "weekdays": [0]}).get_json()

    response = client.post(f"/api/goals/{goal['id']}/stop")

    assert response.status_code == 200
    assert response.get_json()["archived_at"] is not None


def test_remove_goal_deletes_it(client):
    goal = client.post("/api/goals", json={"text": "g"}).get_json()

    assert client.delete(f"/api/goals/{goal['id']}").status_code == 204
    assert client.get("/api/goals").get_json()["goals"] == []


def test_idea_goals_route_404s_for_a_missing_idea(client):
    response = client.get("/api/ideas/999/goals")

    assert response.status_code == 404
    assert response.get_json() == {"error": "not found"}
