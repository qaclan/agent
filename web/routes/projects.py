import os
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, set_active_project_id

bp = Blueprint('projects', __name__)


@bp.route('/api/projects', methods=['GET'])
def list_projects():
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, name, created_at FROM projects ORDER BY created_at DESC"
        ).fetchall()
        projects = [dict(r) for r in rows]
        return jsonify({"ok": True, "projects": projects})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/projects', methods=['POST'])
def create_project():
    try:
        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Project name is required"}), 400

        conn = get_conn()
        project_id = generate_id("proj")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
            (project_id, name, now),
        )
        conn.commit()

        set_active_project_id(project_id)

        from cli.sync import sync_project_to_cloud
        sync_project_to_cloud(project_id, name)

        return jsonify({"ok": True, "id": project_id, "name": name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/projects/active', methods=['GET'])
def get_active_project():
    try:
        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"ok": True, "id": None, "name": None})

        conn = get_conn()
        row = conn.execute(
            "SELECT id, name FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return jsonify({"ok": True, "id": None, "name": None})

        return jsonify({"ok": True, "id": row["id"], "name": row["name"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/projects/active', methods=['POST'])
def set_active_project():
    try:
        data = request.get_json(force=True)
        project_id = data.get("id", "").strip()
        if not project_id:
            return jsonify({"ok": False, "error": "Project id is required"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id, name FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Project {project_id} not found"}), 404

        set_active_project_id(project_id)
        return jsonify({"ok": True, "id": row["id"], "name": row["name"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Project {project_id} not found"}), 404

        # Delete script files from disk
        scripts = conn.execute(
            "SELECT file_path FROM scripts WHERE project_id = ?", (project_id,)
        ).fetchall()
        for s in scripts:
            if s["file_path"] and os.path.exists(s["file_path"]):
                os.unlink(s["file_path"])

        # ON DELETE CASCADE handles all child tables
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()

        # Clear active project if it was this one
        if get_active_project_id() == project_id:
            set_active_project_id(None)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
