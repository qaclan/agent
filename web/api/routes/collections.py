from __future__ import annotations
import io
import logging
import zipfile
from flask import Blueprint, request, jsonify, send_file
from cli.config import get_active_project_id
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from web.api.services.collection_service import CollectionService
from web.api.services.runner_service import RunnerService

logger = logging.getLogger("qaclan.routes.collections")
bp = Blueprint("api_collections", __name__)
_svc = CollectionService()
_runner_svc = RunnerService()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/collections", methods=["GET"])
def list_collections():
    try:
        return jsonify({"ok": True, "collections": _svc.list(_project_id())})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_collections")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections", methods=["POST"])
def create_collection():
    try:
        data = request.get_json(force=True)
        col = _svc.create(_project_id(), data.get("name", ""), data.get("description"))
        return jsonify({"ok": True, "collection": col}), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["GET"])
def get_collection(col_id):
    try:
        return jsonify({"ok": True, "collection": _svc.get(col_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["PUT"])
def update_collection(col_id):
    try:
        data = request.get_json(force=True)
        col = _svc.update(col_id, _project_id(), data.get("name", ""), data.get("description"))
        return jsonify({"ok": True, "collection": col})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["DELETE"])
def delete_collection(col_id):
    try:
        _svc.delete(col_id, _project_id())
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["PATCH"])
def patch_collection(col_id):
    try:
        pid = _project_id()
        col = CollectionRepo().get(col_id, pid)
        if not col:
            return jsonify({"ok": False, "error": "Not found"}), 404
        body = request.get_json(force=True) or {}
        CollectionRepo().update(
            col_id,
            body.get("name", col["name"]),
            body.get("description", col.get("description")),
            body.get("env_name", col.get("env_name")),
            body.get("auth_type", col.get("auth_type", "none")),
            body.get("auth_config", col.get("auth_config", "{}")),
        )
        return jsonify({"ok": True, "collection": CollectionRepo().get(col_id, pid)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("patch_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/run", methods=["POST"])
def run_collection(col_id):
    try:
        data = request.get_json(force=True) or {}
        env_name = data.get("env_name") or None
        seed_vars = data.get("seed_vars") or None
        pid = _project_id()
        run_id, already_running = _runner_svc.start_collection_run(
            col_id, pid, env_name=env_name, seed_vars=seed_vars
        )
        return jsonify({"ok": True, "run_id": run_id, "status": "RUNNING",
                        "already_running": already_running})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("run_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/vars", methods=["GET"])
def list_collection_vars(col_id):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True, "vars": CollectionVarsRepo().list(col_id)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_collection_vars")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/vars/<path:key>", methods=["PUT"])
def upsert_collection_var(col_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        body = request.get_json(force=True) or {}
        result = CollectionVarsRepo().upsert(col_id, key, body.get("initial_value", ""))
        return jsonify({"ok": True, "var": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("upsert_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/vars/<path:key>", methods=["DELETE"])
def delete_collection_var(col_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        CollectionVarsRepo().delete(col_id, key)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/export", methods=["POST"])
def export_collection(col_id):
    """Export collection to Bruno .bru files, returned as a zip."""
    try:
        col = _svc.get(col_id, _project_id())
        requests = col.get("requests", [])

        from cli.api_discovery.bruno_parser import request_to_bru
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for req in requests:
                content = request_to_bru(req)
                safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in req.get("name", "request"))
                zf.writestr(f"{col['name']}/{safe_name}.bru", content)

        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{col['name']}.zip",
        )
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("export_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
