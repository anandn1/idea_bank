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
        conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        conn.commit()
        return "", 204


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
