from __future__ import annotations
import io
import json
import logging
import zipfile
from flask import Blueprint, request, jsonify, send_file
from cli.config import get_active_project_id
from cli.sync_queue import enqueue
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from web.api.repositories.folder_repo import FolderRepo
from web.api.services.collection_service import CollectionService
from web.api.services.runner_service import RunnerService

logger = logging.getLogger("qaclan.routes.collections")
bp = Blueprint("api_collections", __name__)
_svc = CollectionService()
_runner_svc = RunnerService()

MASKED_DISPLAY = "•" * 8


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
        enqueue("api_collection", col["id"], "upsert")
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
        enqueue("api_collection", col_id, "upsert")
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
        enqueue("api_collection", col_id, "delete")
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
        if "schema_check_default" in body:
            CollectionRepo().set_schema_check_default(col_id, body.get("schema_check_default"))
            # Global toggle overwrites all per-request overrides: reset them to
            # 'inherit' so every request follows the collection default.
            for changed_req_id in CollectionRepo().reset_schema_check_overrides(col_id):
                enqueue("api_request", changed_req_id, "upsert")
        enqueue("api_collection", col_id, "upsert")
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
        rows = CollectionVarsRepo().list(col_id)
        for v in rows:
            if v.get("is_secret"):
                v["initial_value"] = MASKED_DISPLAY
        return jsonify({"ok": True, "vars": rows})
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
        result = CollectionVarsRepo().upsert(
            col_id, key, body.get("initial_value", ""),
            is_secret=bool(body.get("is_secret", False)),
            unchanged=bool(body.get("unchanged", False)),
        )
        enqueue("collection_vars", col_id, "upsert")
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
        enqueue("collection_vars", col_id, "upsert")
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/vars/<path:key>/reveal", methods=["GET"])
def reveal_collection_var(col_id, key):
    """Return the decrypted plaintext for a single secret collection var."""
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        value = CollectionVarsRepo().reveal(col_id, key)
        if value is None:
            return jsonify({"ok": False, "error": f'Variable "{key}" not found'}), 404
        resp = jsonify({"ok": True, "key": key, "value": value})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("reveal_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/export", methods=["POST"])
def export_collection(col_id):
    """Export collection to Bruno .bru files (zip) or a Postman v2.1 JSON
    file. Query param: ?format=bruno|postman (default bruno)."""
    try:
        fmt = request.args.get("format", "bruno")
        pid = _project_id()
        col = _svc.get(col_id, pid)
        requests = col.get("requests", [])
        folders = FolderRepo().list_for_collection(col_id)
        collection_vars = CollectionVarsRepo().list(col_id)

        if fmt == "postman":
            from cli.api_discovery.postman_exporter import to_postman_collection
            exported = to_postman_collection(col, requests, folders, collection_vars)
            buf = io.BytesIO(json.dumps(exported, indent=2).encode("utf-8"))
            buf.seek(0)
            return send_file(
                buf,
                mimetype="application/json",
                as_attachment=True,
                download_name=f"{col['name']}.postman_collection.json",
            )

        from cli.api_discovery.bruno_parser import export_bruno_tree
        tree = export_bruno_tree(col, requests, folders, collection_vars)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path, content in tree.items():
                zf.writestr(f"{col['name']}/{rel_path}", content)

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


@bp.route("/api/collections/order", methods=["PUT"])
def reorder_collections():
    try:
        data = request.get_json(force=True) or {}
        ids = data.get("collection_ids", [])
        if not ids:
            return jsonify({"ok": False, "error": "collection_ids array is required"}), 400
        _svc.reorder(_project_id(), ids)
        for cid in ids:
            enqueue("api_collection", cid, "upsert")
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("reorder_collections")
        return jsonify({"ok": False, "error": str(e)}), 500
