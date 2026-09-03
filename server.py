"""idea-bank-v2 Flask server: JSON API + static single-page GUI."""

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
        return jsonify([dict(row) for row in rows])


@app.post("/api/ideas")
def create_idea():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    idea_id = dbutil.add_idea(text, status="inbox")
    with dbutil.connection() as conn:
        return jsonify(dbutil.get_idea(conn, idea_id)), 201


@app.patch("/api/ideas/<int:idea_id>")
def update_idea(idea_id):
    payload = request.get_json(silent=True) or {}
    with dbutil.connection() as conn:
        if dbutil.get_idea(conn, idea_id) is None:
            return jsonify({"error": "not found"}), 404

        fields, values = [], []

        if "status" in payload:
            status = payload["status"]
            if status not in dbutil.STATUSES:
                return jsonify({"error": f"invalid status: {status}"}), 400
            fields.append("status = ?")
            values.append(status)

        if "text" in payload:
            text = (payload["text"] or "").strip()
            if not text:
                return jsonify({"error": "text cannot be empty"}), 400
            fields.append("text = ?")
            values.append(text)

        if "notes" in payload:
            fields.append("notes = ?")
            values.append(payload["notes"])

        if not fields:
            return jsonify({"error": "no updatable fields provided"}), 400

        fields.append("updated_at = ?")
        values.append(dbutil.now_str())
        values.append(idea_id)

        conn.execute(f"UPDATE ideas SET {', '.join(fields)} WHERE id = ?", values)
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
