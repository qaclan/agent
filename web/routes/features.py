import os
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, SCRIPTS_DIR

bp = Blueprint('features', __name__)


def _require_active_project():
    """Return project_id or None. Caller should check and return 400 if None."""
    return get_active_project_id()


@bp.route('/api/features', methods=['GET'])
def list_features():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        rows = conn.execute(
            "SELECT f.id, f.name, f.channel, f.description, f.source_url, f.created_at, "
            "(SELECT COUNT(*) FROM scripts s WHERE s.feature_id = f.id) AS script_count "
            "FROM features f WHERE f.project_id = ? AND f.channel = 'web' "
            "ORDER BY f.created_at DESC",
            (project_id,),
        ).fetchall()

        features = [dict(r) for r in rows]
        return jsonify({"ok": True, "features": features})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/features', methods=['POST'])
def create_feature():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Feature name is required"}), 400

        conn = get_conn()
        feature_id = generate_id("feat")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO features (id, project_id, channel, name, description, source_url, created_at) "
            "VALUES (?, ?, 'web', ?, ?, ?, ?)",
            (feature_id, project_id, name,
             data.get("description", ""), data.get("source_url", ""), now),
        )
        conn.commit()

        from cli.sync import sync_feature_to_cloud
        sync_feature_to_cloud(feature_id, name, project_id)

        return jsonify({"ok": True, "id": feature_id, "name": name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/features/<feature_id>', methods=['PUT'])
def update_feature(feature_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Feature name is required"}), 400

        conn = get_conn()
        feat = conn.execute(
            "SELECT * FROM features WHERE id = ? AND project_id = ?",
            (feature_id, project_id),
        ).fetchone()
        if not feat:
            return jsonify({"ok": False, "error": f"Feature {feature_id} not found"}), 404

        conn.execute("UPDATE features SET name = ? WHERE id = ?", (name, feature_id))
        conn.commit()

        from cli.sync import sync_feature_to_cloud
        sync_feature_to_cloud(feature_id, name, project_id)

        return jsonify({"ok": True, "id": feature_id, "name": name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/features/<feature_id>', methods=['DELETE'])
def delete_feature(feature_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id FROM features WHERE id = ? AND project_id = ?",
            (feature_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Feature {feature_id} not found"}), 404

        # Delete script files from disk
        scripts = conn.execute(
            "SELECT id, file_path FROM scripts WHERE feature_id = ?", (feature_id,)
        ).fetchall()
        for s in scripts:
            file_path = s["file_path"]
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)

        # Delete scripts from DB
        conn.execute("DELETE FROM scripts WHERE feature_id = ?", (feature_id,))

        # Delete feature
        conn.execute("DELETE FROM features WHERE id = ?", (feature_id,))
        conn.commit()

        from cli.sync import delete_feature_from_cloud
        delete_feature_from_cloud(feature_id)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
