from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from cli.config import get_active_project_id
from cli.sync_queue import enqueue
from web.api.services.folder_service import FolderService

logger = logging.getLogger("qaclan.routes.folders")
bp = Blueprint("api_folders_bp", __name__)
_svc = FolderService()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/collections/<col_id>/tree", methods=["GET"])
def get_collection_tree(col_id):
    try:
        return jsonify({"ok": True, **_svc.tree(col_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_collection_tree")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/folders", methods=["POST"])
def create_folder(col_id):
    try:
        data = request.get_json(force=True) or {}
        folder = _svc.create(_project_id(), col_id, data.get("name", ""), data.get("parent_folder_id"))
        enqueue("api_folder", folder["id"], "upsert")
        return jsonify({"ok": True, "folder": folder}), 201
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_folder")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-folders/<folder_id>", methods=["PATCH"])
def update_folder(folder_id):
    try:
        data = request.get_json(force=True) or {}
        folder = _svc.update(folder_id, _project_id(), data)
        enqueue("api_folder", folder_id, "upsert")
        return jsonify({"ok": True, "folder": folder})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_folder")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-folders/<folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    try:
        _svc.delete(folder_id, _project_id())
        enqueue("api_folder", folder_id, "delete")
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_folder")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/tree-order", methods=["PUT"])
def reorder_tree(col_id):
    try:
        data = request.get_json(force=True) or {}
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "items array is required"}), 400
        _svc.reorder(col_id, _project_id(), data.get("parent_folder_id"), items)
        from cli.db import get_conn
        conn = get_conn()
        for row in conn.execute("SELECT id FROM api_folders WHERE collection_id = ?", (col_id,)).fetchall():
            enqueue("api_folder", row["id"], "upsert")
        for row in conn.execute("SELECT id FROM api_requests WHERE collection_id = ?", (col_id,)).fetchall():
            enqueue("api_request", row["id"], "upsert")
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("reorder_tree")
        return jsonify({"ok": False, "error": str(e)}), 500
