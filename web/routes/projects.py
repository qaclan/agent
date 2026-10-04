import os
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, set_active_project_id
from cli import timeout_budget

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

        existing = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        if existing:
            return jsonify({"ok": False, "error": f'Project "{name}" already exists'}), 409

        project_id = generate_id("proj")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
            (project_id, name, now),
        )
        conn.commit()

        set_active_project_id(project_id)

        from cli.sync_queue import enqueue
        enqueue("project", project_id, "upsert")

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


def _settings_payload(row):
    return {k: row[k] for k in timeout_budget.SETTING_KEYS}


def _settings_defaults():
    """Built-in values the UI shows next to 'inherit' / 'auto' choices."""
    return {
        "wait_timeout": timeout_budget.DEFAULT_WAIT_TIMEOUT,
        "max_script_time": timeout_budget.DEFAULT_MAX_SCRIPT_TIME,
        "allowed_wait_timeouts": sorted(timeout_budget.ALLOWED_WAIT_TIMEOUTS),
        "min_max_script_time": timeout_budget.MIN_MAX_SCRIPT_TIME,
        "max_max_script_time": timeout_budget.MAX_MAX_SCRIPT_TIME,
        "min_test_timeout": timeout_budget.MIN_FIXED_TEST_TIMEOUT,
    }


@bp.route('/api/projects/<project_id>/settings', methods=['GET'])
def get_project_settings(project_id):
    try:
        conn = get_conn()
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Project {project_id} not found"}), 404
        return jsonify({"ok": True, "settings": _settings_payload(row), "defaults": _settings_defaults()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/projects/<project_id>/settings', methods=['PUT'])
def update_project_settings(project_id):
    """Update timeout defaults. Only keys present in the body change; null
    clears a value (wait/max -> built-in default, test_timeout -> auto)."""
    try:
        data = request.get_json(force=True) or {}
        conn = get_conn()
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Project {project_id} not found"}), 404

        payload = {k: data[k] for k in timeout_budget.SETTING_KEYS if k in data}
        updates, err = timeout_budget.validate_settings(payload, current=row, parent=None)
        if err:
            return jsonify({"ok": False, "error": err}), 400

        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", (*updates.values(), project_id))
            conn.commit()

            from cli.sync_queue import enqueue
            enqueue("project", project_id, "upsert")

        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return jsonify({"ok": True, "settings": _settings_payload(row)})
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

        from cli.sync_queue import enqueue
        enqueue("project", project_id, "delete")

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
