from __future__ import annotations
import logging
from flask import Blueprint, jsonify, request, Response
from cli.config import get_active_project_id
from web.api.repositories.doc_repo import DocRepo

logger = logging.getLogger("qaclan.routes.docs")
bp = Blueprint("api_docs", __name__)
_repo = DocRepo()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


def _project_name(project_id: str) -> str:
    """Look up project name from DB for use in OpenAPI title."""
    try:
        from cli.db import get_conn
        conn = get_conn()
        row = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
        return row["name"] if row else "API"
    except Exception:
        return "API"


@bp.route("/api/docs", methods=["GET"])
def list_docs():
    try:
        entries = _repo.list(_project_id())
        return jsonify({"ok": True, "entries": entries})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_docs")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/docs/<entry_id>", methods=["GET"])
def get_doc(entry_id):
    try:
        entry = _repo.get(_project_id(), entry_id)
        if not entry:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True, "entry": entry})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_doc")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/docs/<entry_id>", methods=["DELETE"])
def delete_doc(entry_id):
    try:
        deleted = _repo.delete(_project_id(), entry_id)
        if not deleted:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_doc")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/docs/export/openapi", methods=["GET"])
def export_openapi():
    try:
        from cli.api_discovery.openapi_exporter import export_openapi_yaml
        pid = _project_id()
        project_name = _project_name(pid)
        entries = _repo.list(pid)
        yaml_str = export_openapi_yaml(entries, project_name)
        return Response(
            yaml_str,
            mimetype='application/x-yaml',
            headers={'Content-Disposition': 'attachment; filename="openapi.yaml"'},
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("export_openapi")
        return jsonify({"ok": False, "error": str(e)}), 500
