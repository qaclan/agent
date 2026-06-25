from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from web.api.repositories.api_run_repo import ApiRunRepo

logger = logging.getLogger("qaclan.routes.api_runs")
bp = Blueprint("api_runs_bp", __name__)
_repo = ApiRunRepo()


@bp.route("/api/api-runs", methods=["GET"])
def list_api_runs():
    try:
        suite_run_id = request.args.get("suite_run_id", "")
        if not suite_run_id:
            return jsonify({"ok": False, "error": "suite_run_id query param required"}), 400
        rows = _repo.list_by_suite_run(suite_run_id)
        return jsonify({"ok": True, "api_runs": rows})
    except Exception as e:
        logger.exception("list_api_runs")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-runs/<run_id>", methods=["GET"])
def get_api_run(run_id):
    try:
        row = _repo.get(run_id)
        if row is None:
            return jsonify({"ok": False, "error": f"API run {run_id} not found"}), 404
        return jsonify({"ok": True, "api_run": row})
    except Exception as e:
        logger.exception("get_api_run")
        return jsonify({"ok": False, "error": str(e)}), 500
