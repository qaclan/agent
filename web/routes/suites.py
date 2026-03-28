from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id

bp = Blueprint('suites', __name__)


def _require_active_project():
    return get_active_project_id()


@bp.route('/api/suites', methods=['GET'])
def list_suites():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        rows = conn.execute(
            "SELECT su.id, su.name, su.channel, su.first_run_at, su.last_run_at, "
            "su.last_run_status, su.created_at, "
            "(SELECT COUNT(*) FROM suite_items si WHERE si.suite_id = su.id) AS script_count "
            "FROM suites su WHERE su.project_id = ? "
            "ORDER BY su.created_at DESC",
            (project_id,),
        ).fetchall()

        suites = [dict(r) for r in rows]
        return jsonify({"ok": True, "suites": suites})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites/<suite_id>', methods=['GET'])
def get_suite(suite_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id, name, channel, first_run_at, last_run_at, last_run_status, created_at "
            "FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404

        suite = dict(row)

        # Load ordered scripts
        items = conn.execute(
            "SELECT si.script_id, s.name, si.order_index "
            "FROM suite_items si JOIN scripts s ON si.script_id = s.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        suite["scripts"] = [dict(i) for i in items]

        return jsonify({"ok": True, "suite": suite})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites', methods=['POST'])
def create_suite():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Suite name is required"}), 400

        conn = get_conn()
        suite_id = generate_id("suite")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO suites (id, project_id, channel, name, created_at) "
            "VALUES (?, ?, 'web', ?, ?)",
            (suite_id, project_id, name, now),
        )
        conn.commit()

        return jsonify({"ok": True, "id": suite_id, "name": name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites/<suite_id>/scripts', methods=['POST'])
def add_script_to_suite(suite_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        script_id = data.get("script_id", "").strip()
        if not script_id:
            return jsonify({"ok": False, "error": "script_id is required"}), 400

        conn = get_conn()

        # Verify suite exists
        suite = conn.execute(
            "SELECT id FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not suite:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404

        # Verify script exists
        script = conn.execute(
            "SELECT id FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not script:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        # Get next order_index
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) AS max_idx FROM suite_items WHERE suite_id = ?",
            (suite_id,),
        ).fetchone()["max_idx"]

        item_id = generate_id("si")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO suite_items (id, suite_id, script_id, order_index, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (item_id, suite_id, script_id, max_order + 1, now),
        )
        conn.commit()

        return jsonify({"ok": True, "id": item_id, "order_index": max_order + 1}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites/<suite_id>/scripts/<script_id>', methods=['DELETE'])
def remove_script_from_suite(suite_id, script_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()

        row = conn.execute(
            "SELECT si.id FROM suite_items si "
            "JOIN suites su ON si.suite_id = su.id "
            "WHERE si.suite_id = ? AND si.script_id = ? AND su.project_id = ?",
            (suite_id, script_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Script not found in suite"}), 404

        conn.execute(
            "DELETE FROM suite_items WHERE suite_id = ? AND script_id = ?",
            (suite_id, script_id),
        )
        conn.commit()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites/<suite_id>/order', methods=['PUT'])
def reorder_suite_scripts(suite_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        script_ids = data.get("script_ids", [])
        if not script_ids:
            return jsonify({"ok": False, "error": "script_ids array is required"}), 400

        conn = get_conn()

        # Verify suite exists
        suite = conn.execute(
            "SELECT id FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not suite:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404

        for idx, sid in enumerate(script_ids):
            conn.execute(
                "UPDATE suite_items SET order_index = ? WHERE suite_id = ? AND script_id = ?",
                (idx, suite_id, sid),
            )

        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites/<suite_id>', methods=['DELETE'])
def delete_suite(suite_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT id FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404

        # Delete suite_items first, then suite
        conn.execute("DELETE FROM suite_items WHERE suite_id = ?", (suite_id,))
        conn.execute("DELETE FROM suites WHERE id = ?", (suite_id,))
        conn.commit()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
