import os
from pathlib import Path
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, SCRIPTS_DIR

bp = Blueprint('scripts', __name__)


def _require_active_project():
    return get_active_project_id()


@bp.route('/api/scripts', methods=['GET'])
def list_scripts():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        feature_id = request.args.get("feature_id")

        if feature_id:
            rows = conn.execute(
                "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
                "s.channel, s.source, s.created_at "
                "FROM scripts s JOIN features f ON s.feature_id = f.id "
                "WHERE s.project_id = ? AND s.feature_id = ? "
                "ORDER BY s.created_at DESC",
                (project_id, feature_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
                "s.channel, s.source, s.created_at "
                "FROM scripts s JOIN features f ON s.feature_id = f.id "
                "WHERE s.project_id = ? "
                "ORDER BY s.created_at DESC",
                (project_id,),
            ).fetchall()

        scripts = [dict(r) for r in rows]
        return jsonify({"ok": True, "scripts": scripts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>', methods=['GET'])
def get_script(script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
            "s.channel, s.source, s.file_path, s.created_at "
            "FROM scripts s JOIN features f ON s.feature_id = f.id "
            "WHERE s.id = ? AND s.project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        script = dict(row)

        # Read file content from disk
        content = ""
        file_path = script.get("file_path", "")
        if file_path and os.path.exists(file_path):
            with open(file_path, "r") as f:
                content = f.read()
        script["content"] = content

        return jsonify({"ok": True, "script": script})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts', methods=['POST'])
def create_script():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        feature_id = data.get("feature_id", "").strip()
        content = data.get("content", "")

        if not name:
            return jsonify({"ok": False, "error": "Script name is required"}), 400
        if not feature_id:
            return jsonify({"ok": False, "error": "Feature ID is required"}), 400

        conn = get_conn()

        # Verify feature exists and belongs to active project
        feat = conn.execute(
            "SELECT id FROM features WHERE id = ? AND project_id = ?",
            (feature_id, project_id),
        ).fetchone()
        if not feat:
            return jsonify({"ok": False, "error": f"Feature {feature_id} not found"}), 404

        script_id = generate_id("script")
        now = datetime.now(timezone.utc).isoformat()

        # Write script file to disk
        scripts_dir = Path(SCRIPTS_DIR)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(scripts_dir / f"{script_id}.py")
        with open(file_path, "w") as f:
            f.write(content)

        conn.execute(
            "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, created_at) "
            "VALUES (?, ?, ?, 'web', ?, ?, 'WEB_CREATED', ?)",
            (script_id, feature_id, project_id, name, file_path, now),
        )
        conn.commit()

        from cli.sync import sync_script_to_cloud
        sync_script_to_cloud(script_id, name)

        return jsonify({"ok": True, "id": script_id, "name": name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>', methods=['PUT'])
def update_script(script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id, file_path FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        data = request.get_json(force=True)
        name = data.get("name")
        content = data.get("content")

        if name is not None:
            name = name.strip()
            if not name:
                return jsonify({"ok": False, "error": "Script name cannot be empty"}), 400
            conn.execute(
                "UPDATE scripts SET name = ? WHERE id = ?", (name, script_id)
            )

        if content is not None:
            file_path = row["file_path"]
            if file_path:
                with open(file_path, "w") as f:
                    f.write(content)

        conn.commit()
        return jsonify({"ok": True, "id": script_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/record', methods=['POST'])
def record_script_route():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        feature_id = data.get("feature_id", "").strip()
        url = data.get("url", "").strip() or None

        if not name:
            return jsonify({"ok": False, "error": "Script name is required"}), 400
        if not feature_id:
            return jsonify({"ok": False, "error": "Feature ID is required"}), 400

        from cli.commands.web.record import record_script
        script_id, dest = record_script(project_id, feature_id, name, url)
        return jsonify({"ok": True, "id": script_id, "name": name}), 201
    except (ValueError, RuntimeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/scripts/<script_id>', methods=['DELETE'])
def delete_script(script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id, file_path FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        # Delete file from disk
        file_path = row["file_path"]
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)

        # Delete DB row
        conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
        conn.commit()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
