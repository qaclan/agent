from __future__ import annotations
import logging
from flask import Blueprint, jsonify, request, Response
from cli.config import get_active_project_id
from web.api.repositories.collection_run_repo import CollectionRunRepo

logger = logging.getLogger("qaclan.routes.api_collection_runs")
bp = Blueprint("api_collection_runs_bp", __name__)
_repo = CollectionRunRepo()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/api-collection-runs", methods=["GET"])
def list_api_collection_runs():
    try:
        status_filter = request.args.get("status") or None
        runs = _repo.list_runs(_project_id(), status_filter=status_filter)
        return jsonify({"ok": True, "runs": runs})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_api_collection_runs")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-collection-runs/<run_id>", methods=["GET"])
def get_api_collection_run(run_id):
    try:
        pid = _project_id()
        run = _repo.get_run(run_id, pid)
        if run is None:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404
        return jsonify({"ok": True, "run": run})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_api_collection_run")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-collection-runs/<run_id>/stop", methods=["POST"])
def stop_api_collection_run(run_id):
    try:
        pid = _project_id()
        run = _repo.get_run(run_id, pid)
        if run is None:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404
        if run["status"] != "RUNNING":
            return jsonify({"ok": False, "error": "Run is not RUNNING"}), 400
        _repo.request_stop(run_id)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("stop_api_collection_run")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-collection-runs/<run_id>/report", methods=["GET"])
def download_api_report(run_id):
    try:
        from cli.api_report import generate_api_html_report
        pid = _project_id()
        html_str = generate_api_html_report(run_id, pid)
        view = request.args.get("view") == "1"
        disposition = "inline" if view else "attachment"
        return Response(
            html_str,
            mimetype="text/html",
            headers={
                "Content-Disposition": (
                    f'{disposition}; filename="qaclan-api-report-{run_id}.html"'
                )
            },
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("download_api_report")
        return jsonify({"ok": False, "error": str(e)}), 500
