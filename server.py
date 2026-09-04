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
def update_idea(idea_id):
    payload = request.get_json(silent=True) or {}
    with dbutil.connection() as conn:
        if dbutil.get_idea(conn, idea_id) is None:
            return jsonify({"error": "not found"}), 404

        set_clauses, values = [], []

        if "status" in payload:
            status = payload["status"]
            if status not in dbutil.STATUSES:
                return jsonify({"error": f"invalid status: {status}"}), 400
            set_clauses.append("status = ?")
            values.append(status)

        if "text" in payload:
            text = (payload["text"] or "").strip()
            if not text:
                return jsonify({"error": "text cannot be empty"}), 400
            set_clauses.append("text = ?")
            values.append(text)

        if "notes" in payload:
            set_clauses.append("notes = ?")
            values.append(payload["notes"])

        if "fields" in payload:
            idea_fields = payload["fields"]
            if idea_fields is not None and not isinstance(idea_fields, dict):
                return jsonify({"error": "fields must be an object"}), 400
            set_clauses.append("fields = ?")
            values.append(dbutil.encode_fields(idea_fields))

        if not set_clauses:
            return jsonify({"error": "no updatable fields provided"}), 400

        set_clauses.append("updated_at = ?")
        values.append(dbutil.now_str())
        values.append(idea_id)

        conn.execute(f"UPDATE ideas SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()

        return jsonify(dbutil.get_idea(conn, idea_id))


@app.delete("/api/ideas/<int:idea_id>")
def delete_idea(idea_id):
    with dbutil.connection() as conn:
        dbutil.remove_goals_for_idea(conn, idea_id)
        conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        conn.commit()
        return "", 204


@app.get("/api/goals")
def list_goals():
    date = request.args.get("date") or dbutil.today_str()
    with dbutil.connection() as conn:
        goals = dbutil.goals_for_date(conn, date)
        return jsonify({"date": date, "goals": goals})


@app.post("/api/goals")
def create_goal():
    payload = request.get_json(silent=True) or {}
    idea_id = payload.get("idea_id")
    if not isinstance(idea_id, int):
        return jsonify({"error": "idea_id is required"}), 400
    date = payload.get("date") or dbutil.today_str()

    with dbutil.connection() as conn:
        goal = dbutil.add_goal(conn, idea_id, date)
        if goal is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(goal), 201


@app.delete("/api/goals/<int:idea_id>")
def remove_goal_route(idea_id):
    date = request.args.get("date") or dbutil.today_str()
    with dbutil.connection() as conn:
        dbutil.remove_goal(conn, idea_id, date)
        return "", 204


@app.get("/api/goals/streak")
def goal_streak():
    with dbutil.connection() as conn:
        info = dbutil.compute_streak(conn)
        info["xp"] = dbutil.total_xp(conn)
        return jsonify(info)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
