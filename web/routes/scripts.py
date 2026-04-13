import json
import logging
import os
import re
from pathlib import Path
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, SCRIPTS_DIR, get_sensitive_field_patterns, SECRET_CATEGORIES, get_editor_mode

_VAR_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


def _scan_var_keys(content):
    """Extract unique {{KEY}} placeholders from a script body."""
    if not content:
        return []
    seen = []
    for m in _VAR_PLACEHOLDER_RE.finditer(content):
        key = m.group(1)
        if key not in seen:
            seen.append(key)
    return seen

logger = logging.getLogger("qaclan.record")

bp = Blueprint('scripts', __name__)


def _require_active_project():
    return get_active_project_id()


@bp.route('/api/scripts/sensitive-patterns', methods=['GET'])
def get_sensitive_patterns():
    """Return the active sensitive field patterns for client-side field detection."""
    try:
        return jsonify({
            "ok": True,
            "patterns": get_sensitive_field_patterns(),
            "secret_categories": list(SECRET_CATEGORIES),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/settings', methods=['GET'])
def get_settings():
    """Return agent settings the frontend needs on startup."""
    try:
        return jsonify({
            "ok": True,
            "settings": {
                "editor_mode": get_editor_mode(),
            },
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
                "s.channel, s.source, s.created_at, s.created_by "
                "FROM scripts s JOIN features f ON s.feature_id = f.id "
                "WHERE s.project_id = ? AND s.feature_id = ? "
                "ORDER BY s.created_at DESC",
                (project_id, feature_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.id, s.name, s.feature_id, f.name AS feature_name, "
                "s.channel, s.source, s.created_at, s.created_by "
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
            "s.channel, s.source, s.file_path, s.created_at, s.created_by, "
            "s.start_url_key, s.start_url_value, s.var_keys "
            "FROM scripts s JOIN features f ON s.feature_id = f.id "
            "WHERE s.id = ? AND s.project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        script = dict(row)

        # Parse var_keys JSON for the client
        try:
            script["var_keys"] = json.loads(script.get("var_keys") or "[]")
        except (TypeError, ValueError):
            script["var_keys"] = []

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

        from cli.config import get_user_name
        created_by = get_user_name()
        # Scan {{KEY}} placeholders so var_keys is populated for runtime substitution
        var_keys_list = _scan_var_keys(content)
        conn.execute(
            "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, created_at, created_by, var_keys) "
            "VALUES (?, ?, ?, 'web', ?, ?, 'WEB_CREATED', ?, ?, ?)",
            (script_id, feature_id, project_id, name, file_path, now, created_by, json.dumps(var_keys_list)),
        )
        conn.commit()

        from cli.sync_queue import enqueue
        enqueue("script", script_id, "upsert")

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
            # Re-scan {{KEY}} placeholders so var_keys stays in sync with the body
            new_var_keys = _scan_var_keys(content)
            conn.execute(
                "UPDATE scripts SET var_keys = ? WHERE id = ?",
                (json.dumps(new_var_keys), script_id),
            )

        conn.commit()

        from cli.sync_queue import enqueue
        enqueue("script", script_id, "upsert")

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
        env_name = data.get("env_name", "").strip() or None
        url_key = data.get("url_key", "").strip() or None
        path_suffix = data.get("path_suffix", "").strip() or ""

        if not name:
            return jsonify({"ok": False, "error": "Script name is required"}), 400
        if not feature_id:
            return jsonify({"ok": False, "error": "Feature ID is required"}), 400

        # If env+key provided, resolve the actual URL from the env var
        resolved_url_key = None
        resolved_url_key_value = None
        if env_name and url_key:
            conn = get_conn()
            env_row = conn.execute(
                "SELECT id FROM environments WHERE project_id = ? AND name = ?",
                (project_id, env_name),
            ).fetchone()
            if not env_row:
                return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404
            var_row = conn.execute(
                "SELECT value FROM env_vars WHERE environment_id = ? AND key = ?",
                (env_row["id"], url_key),
            ).fetchone()
            if not var_row:
                return jsonify({"ok": False, "error": f"Variable \"{url_key}\" not found in env \"{env_name}\""}), 404
            base_value = (var_row["value"] or "").rstrip("/")
            if not base_value:
                return jsonify({"ok": False, "error": f"Variable \"{url_key}\" has an empty value in env \"{env_name}\""}), 400
            url = base_value + path_suffix
            resolved_url_key = url_key
            resolved_url_key_value = base_value

        logger.info("POST /api/scripts/record: project=%s, feature=%s, name=%s, url=%s, url_key=%s",
                     project_id, feature_id, name, url, resolved_url_key)

        from cli.commands.web.record import record_script
        script_id, dest = record_script(
            project_id, feature_id, name, url,
            url_key=resolved_url_key,
            url_key_value=resolved_url_key_value,
        )
        logger.info("Recording succeeded: script_id=%s, dest=%s", script_id, dest)
        return jsonify({"ok": True, "id": script_id, "name": name}), 201
    except (ValueError, RuntimeError) as e:
        logger.error("Recording failed (expected): %s", e)
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Recording failed (unexpected): %s", e)
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

        from cli.sync_queue import enqueue
        enqueue("script", script_id, "delete")

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
