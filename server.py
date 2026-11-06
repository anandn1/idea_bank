"""idea-bank-v2 Flask server: JSON API + serves the single-page GUI."""

from flask import Flask, jsonify, request, send_from_directory

import dbutil

app = Flask(__name__, static_folder="static", static_url_path="")

PORT = 8420


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/ideas")
def list_ideas():
    with dbutil.connection() as conn:
        rows = conn.execute(
            f"SELECT {dbutil.IDEA_COLUMNS} FROM ideas ORDER BY updated_at DESC"
        ).fetchall()
        return jsonify([dbutil.row_to_idea(row) for row in rows])


@app.get("/api/ideas/<int:idea_id>")
def get_idea_route(idea_id):
    with dbutil.connection() as conn:
        idea = dbutil.get_idea(conn, idea_id)
        if idea is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(idea)


@app.post("/api/ideas")
def create_idea():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    status = payload.get("status", "inbox")
    if status not in dbutil.STATUSES:
        return jsonify({"error": f"invalid status: {status}"}), 400

    idea_fields = payload.get("fields")
    if idea_fields is not None and not isinstance(idea_fields, dict):
        return jsonify({"error": "fields must be an object"}), 400

    idea_id = dbutil.add_idea(text, status=status, fields=idea_fields)
    with dbutil.connection() as conn:
        return jsonify(dbutil.get_idea(conn, idea_id)), 201


@app.patch("/api/ideas/<int:idea_id>")
def update_idea_route(idea_id):
    payload = request.get_json(silent=True) or {}
    with dbutil.connection() as conn:
        if dbutil.get_idea(conn, idea_id) is None:
            return jsonify({"error": "not found"}), 404

        kwargs = {}

        if "status" in payload:
            status = payload["status"]
            if status not in dbutil.STATUSES:
                return jsonify({"error": f"invalid status: {status}"}), 400
            kwargs["status"] = status

        if "text" in payload:
            text = (payload["text"] or "").strip()
            if not text:
                return jsonify({"error": "text cannot be empty"}), 400
            kwargs["text"] = text

        if "notes" in payload:
            kwargs["notes"] = payload["notes"]

        if "fields" in payload:
            idea_fields = payload["fields"]
            if idea_fields is not None and not isinstance(idea_fields, dict):
                return jsonify({"error": "fields must be an object"}), 400
            kwargs["fields"] = idea_fields

        if not kwargs:
            return jsonify({"error": "no updatable fields provided"}), 400

        return jsonify(dbutil.update_idea(conn, idea_id, kwargs))


@app.delete("/api/ideas/<int:idea_id>")
def delete_idea(idea_id):
    with dbutil.connection() as conn:
        dbutil.unlink_goals_from_idea(conn, idea_id)
        conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        conn.commit()
        return "", 204


@app.get("/api/goals")
def list_goals():
    date = request.args.get("date") or dbutil.today_str()
    with dbutil.connection() as conn:
        goals = dbutil.goals_due_on(conn, date)
        return jsonify({"date": date, "goals": goals})


@app.post("/api/goals")
def create_goal():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    idea_ids = payload.get("idea_ids")
    if idea_ids is not None and (
        not isinstance(idea_ids, list)
        or not all(isinstance(i, int) and not isinstance(i, bool) for i in idea_ids)
    ):
        return jsonify({"error": "idea_ids must be a list of integers"}), 400

    weekdays = payload.get("weekdays")
    if weekdays is not None and (
        not isinstance(weekdays, list)
        or not all(
            isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6
            for d in weekdays
        )
    ):
        return (
            jsonify(
                {"error": "weekdays must be a list of integers 0-6 (Mon=0..Sun=6)"}
            ),
            400,
        )
    target_date = payload.get("target_date")
    if weekdays and target_date:
        return (
            jsonify({"error": "target_date doesn't apply to a goal with weekdays"}),
            400,
        )

    with dbutil.connection() as conn:
        goal = dbutil.create_goal(
            conn,
            text,
            idea_ids=idea_ids,
            weekdays=weekdays,
            target_date=target_date,
        )
        if goal is None:
            return jsonify({"error": "no idea with that id"}), 404
        return jsonify(goal), 201


@app.patch("/api/goals/<int:goal_id>")
def update_goal(goal_id):
    payload = request.get_json(silent=True) or {}
    date = payload.get("date") or dbutil.today_str()
    if "completed" not in payload:
        return jsonify({"error": "completed (bool) is required"}), 400

    with dbutil.connection() as conn:
        goal = dbutil.set_goal_done(conn, goal_id, date, bool(payload["completed"]))
        if goal is None:
            return jsonify({"error": "goal not found or not due on that date"}), 404
        return jsonify(goal)


@app.post("/api/goals/<int:goal_id>/stop")
def stop_goal_route(goal_id):
    with dbutil.connection() as conn:
        if not dbutil.stop_goal(conn, goal_id):
            return (
                jsonify({"error": "no weekday schedule to stop, or already stopped"}),
                400,
            )
        return jsonify(dbutil.get_goal(conn, goal_id))


@app.delete("/api/goals/<int:goal_id>")
def remove_goal_route(goal_id):
    with dbutil.connection() as conn:
        dbutil.remove_goal(conn, goal_id)
        return "", 204


@app.post("/api/goals/<int:goal_id>/link")
def link_goal_route(goal_id):
    payload = request.get_json(silent=True) or {}
    idea_id = payload.get("idea_id")
    if not isinstance(idea_id, int) or isinstance(idea_id, bool):
        return jsonify({"error": "idea_id (integer) is required"}), 400

    with dbutil.connection() as conn:
        goal = dbutil.link_goal(conn, goal_id, idea_id)
        if goal is None:
            return jsonify({"error": "no goal or idea with that id"}), 404
        return jsonify(goal)


@app.post("/api/goals/<int:goal_id>/unlink")
def unlink_goal_route(goal_id):
    payload = request.get_json(silent=True) or {}
    idea_id = payload.get("idea_id")
    if not isinstance(idea_id, int) or isinstance(idea_id, bool):
        return jsonify({"error": "idea_id (integer) is required"}), 400

    with dbutil.connection() as conn:
        goal = dbutil.unlink_goal(conn, goal_id, idea_id)
        if goal is None:
            return jsonify({"error": "no goal with that id"}), 404
        return jsonify(goal)


@app.get("/api/goals/completed")
def completed_goals_route():
    with dbutil.connection() as conn:
        return jsonify(dbutil.completed_goals(conn))


@app.get("/api/goals/stats")
def goal_stats_route():
    with dbutil.connection() as conn:
        return jsonify(dbutil.goal_stats(conn))


@app.get("/api/ideas/<int:idea_id>/goals")
def idea_goals_route(idea_id):
    with dbutil.connection() as conn:
        goals = dbutil.goals_for_idea(conn, idea_id)
        if goals is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(goals)


@app.get("/api/goals/streak")
def goal_streak():
    with dbutil.connection() as conn:
        info = dbutil.compute_streak(conn)
        info["xp"] = dbutil.total_xp(conn)
        return jsonify(info)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
