from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id
from cli.crypto import encrypt, decrypt, is_encrypted

MASKED_DISPLAY = "\u2022" * 8

bp = Blueprint('envs', __name__)


def _require_active_project():
    return get_active_project_id()


@bp.route('/api/envs', methods=['GET'])
def list_envs():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        rows = conn.execute(
            "SELECT e.id, e.name, e.created_at, "
            "(SELECT COUNT(*) FROM env_vars ev WHERE ev.environment_id = e.id) AS var_count "
            "FROM environments e WHERE e.project_id = ? "
            "ORDER BY e.created_at DESC",
            (project_id,),
        ).fetchall()

        envs = [dict(r) for r in rows]
        return jsonify({"ok": True, "environments": envs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>', methods=['GET'])
def get_env_vars(env_name):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        env_row = conn.execute(
            "SELECT id, name FROM environments WHERE project_id = ? AND name = ?",
            (project_id, env_name),
        ).fetchone()
        if not env_row:
            return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404

        rows = conn.execute(
            "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
            (env_row["id"],),
        ).fetchall()

        variables = []
        for r in rows:
            v = dict(r)
            if v["is_secret"]:
                v["value"] = MASKED_DISPLAY
            variables.append(v)

        return jsonify({"ok": True, "environment": env_name, "variables": variables})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs', methods=['POST'])
def create_env():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Environment name is required"}), 400

        conn = get_conn()

        # Check for duplicate name
        existing = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, name),
        ).fetchone()
        if existing:
            return jsonify({"ok": False, "error": f"Environment \"{name}\" already exists"}), 409

        env_id = generate_id("env")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO environments (id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (env_id, project_id, name, now),
        )
        conn.commit()

        from cli.sync import sync_environment_to_cloud
        sync_environment_to_cloud(env_id, name, project_id)

        return jsonify({"ok": True, "id": env_id, "name": name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# @bp.route('/api/envs/<env_name>/vars', methods=['POST'])
# def add_or_update_var(env_name):
#     """Add or update a single env var. Kept for reference / future CLI use."""
#     try:
#         project_id = _require_active_project()
#         if not project_id:
#             return jsonify({"ok": False, "error": "No active project"}), 400
#
#         conn = get_conn()
#         env_row = conn.execute(
#             "SELECT id FROM environments WHERE project_id = ? AND name = ?",
#             (project_id, env_name),
#         ).fetchone()
#         if not env_row:
#             return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404
#
#         data = request.get_json(force=True)
#         key = data.get("key", "").strip()
#         value = data.get("value", "")
#         is_secret = int(data.get("is_secret", 0))
#
#         if not key:
#             return jsonify({"ok": False, "error": "Variable key is required"}), 400
#
#         environment_id = env_row["id"]
#
#         existing = conn.execute(
#             "SELECT id FROM env_vars WHERE environment_id = ? AND key = ?",
#             (environment_id, key),
#         ).fetchone()
#
#         if existing:
#             conn.execute(
#                 "UPDATE env_vars SET value = ?, is_secret = ? WHERE id = ?",
#                 (value, is_secret, existing["id"]),
#             )
#             conn.commit()
#             from cli.sync import sync_env_vars_to_cloud
#             sync_env_vars_to_cloud(environment_id)
#             return jsonify({"ok": True, "id": existing["id"], "action": "updated"})
#         else:
#             var_id = generate_id("evar")
#             conn.execute(
#                 "INSERT INTO env_vars (id, environment_id, key, value, is_secret) "
#                 "VALUES (?, ?, ?, ?, ?)",
#                 (var_id, environment_id, key, value, is_secret),
#             )
#             conn.commit()
#             from cli.sync import sync_env_vars_to_cloud
#             sync_env_vars_to_cloud(environment_id)
#             return jsonify({"ok": True, "id": var_id, "action": "created"}), 201
#     except Exception as e:
#         return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>/vars', methods=['POST'])
def update_vars(env_name):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        env_row = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, env_name),
        ).fetchone()
        if not env_row:
            return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404

        data = request.get_json(force=True)
        vars_list = data.get("vars", [])

        environment_id = env_row["id"]

        # Snapshot existing values to preserve unchanged secrets (upsert pattern)
        existing_by_key = {
            r["key"]: r["value"]
            for r in conn.execute(
                "SELECT key, value FROM env_vars WHERE environment_id = ?",
                (environment_id,),
            ).fetchall()
        }

        rows = []
        for v in vars_list:
            key = v.get("key", "").strip()
            if not key:
                continue
            is_secret = int(v.get("is_secret", 0))
            unchanged = bool(v.get("unchanged"))
            if unchanged and is_secret:
                # UI signalled no edit — retain existing ciphertext
                value = existing_by_key.get(key, "")
            else:
                raw = v.get("value", "") or ""
                if is_secret and raw and not is_encrypted(raw):
                    value = encrypt(raw)
                else:
                    value = raw
            rows.append((generate_id("evar"), environment_id, key, value, is_secret))

        conn.execute("DELETE FROM env_vars WHERE environment_id = ?", (environment_id,))
        conn.executemany(
            "INSERT INTO env_vars (id, environment_id, key, value, is_secret) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

        from cli.sync import sync_env_vars_to_cloud
        sync_env_vars_to_cloud(environment_id)

        return jsonify({"ok": True, "count": len([v for v in vars_list if v.get("key", "").strip()])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>/vars/append', methods=['POST'])
def append_vars(env_name):
    """Add vars that don't already exist in this environment. Skips duplicates."""
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        env_row = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, env_name),
        ).fetchone()
        if not env_row:
            return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404

        data = request.get_json(force=True)
        vars_list = data.get("vars", [])
        environment_id = env_row["id"]

        # Load existing keys to skip duplicates
        existing_keys = set(
            r["key"] for r in conn.execute(
                "SELECT key FROM env_vars WHERE environment_id = ?", (environment_id,)
            ).fetchall()
        )

        new_vars = [
            v for v in vars_list
            if v.get("key", "").strip() and v["key"].strip() not in existing_keys
        ]

        if new_vars:
            def _prep_value(v):
                raw = v.get("value", "") or ""
                is_secret = int(v.get("is_secret", 0))
                if is_secret and raw and not is_encrypted(raw):
                    return encrypt(raw)
                return raw
            rows = [
                (generate_id("evar"), environment_id, v["key"].strip(), _prep_value(v), int(v.get("is_secret", 0)))
                for v in new_vars
            ]
            conn.executemany(
                "INSERT INTO env_vars (id, environment_id, key, value, is_secret) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()

            from cli.sync import sync_env_vars_to_cloud
            sync_env_vars_to_cloud(environment_id)

        return jsonify({"ok": True, "added": len(new_vars)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>/copy', methods=['POST'])
def copy_env(env_name):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        src_env = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, env_name),
        ).fetchone()
        if not src_env:
            return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404

        data = request.get_json(force=True)
        new_name = data.get("new_name", "").strip()
        if not new_name:
            return jsonify({"ok": False, "error": "New environment name is required"}), 400

        existing = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, new_name),
        ).fetchone()
        if existing:
            return jsonify({"ok": False, "error": f"Environment \"{new_name}\" already exists"}), 409

        # Create new environment
        new_env_id = generate_id("env")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO environments (id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (new_env_id, project_id, new_name, now),
        )

        # Copy all vars from source
        src_vars = conn.execute(
            "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
            (src_env["id"],),
        ).fetchall()
        rows = [
            (generate_id("evar"), new_env_id, v["key"], v["value"], v["is_secret"])
            for v in src_vars
        ]
        conn.executemany(
            "INSERT INTO env_vars (id, environment_id, key, value, is_secret) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

        from cli.sync import sync_environment_to_cloud, sync_env_vars_to_cloud
        sync_environment_to_cloud(new_env_id, new_name, project_id)
        sync_env_vars_to_cloud(new_env_id)

        return jsonify({"ok": True, "id": new_env_id, "name": new_name}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>/vars/<key>/reveal', methods=['GET'])
def reveal_var(env_name, key):
    """Return the decrypted plaintext for a single secret var.
    Used by the UI when a user unticks the secret checkbox.
    """
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        row = get_conn().execute(
            "SELECT ev.value, ev.is_secret "
            "FROM env_vars ev JOIN environments e ON ev.environment_id = e.id "
            "WHERE e.project_id = ? AND e.name = ? AND ev.key = ?",
            (project_id, env_name, key),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Variable \"{key}\" not found"}), 404

        value = row["value"] or ""
        if row["is_secret"] and value:
            value = decrypt(value)

        resp = jsonify({"ok": True, "key": key, "value": value})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>/vars/<key>', methods=['DELETE'])
def delete_var(env_name, key):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        env_row = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, env_name),
        ).fetchone()
        if not env_row:
            return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404

        existing = conn.execute(
            "SELECT id FROM env_vars WHERE environment_id = ? AND key = ?",
            (env_row["id"], key),
        ).fetchone()
        if not existing:
            return jsonify({"ok": False, "error": f"Variable \"{key}\" not found"}), 404

        conn.execute("DELETE FROM env_vars WHERE id = ?", (existing["id"],))
        conn.commit()

        from cli.sync import sync_env_vars_to_cloud
        sync_env_vars_to_cloud(env_row["id"])

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/envs/<env_name>', methods=['DELETE'])
def delete_env(env_name):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        env_row = conn.execute(
            "SELECT id FROM environments WHERE project_id = ? AND name = ?",
            (project_id, env_name),
        ).fetchone()
        if not env_row:
            return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404

        environment_id = env_row["id"]

        # Delete env_vars first, then environment
        conn.execute("DELETE FROM env_vars WHERE environment_id = ?", (environment_id,))
        conn.execute("DELETE FROM environments WHERE id = ?", (environment_id,))
        conn.commit()

        from cli.sync import delete_environment_from_cloud
        delete_environment_from_cloud(environment_id)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
