from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from cli.config import get_active_project_id
from cli.sync_queue import enqueue
from web.api.services.request_service import RequestService
from web.api.services.runner_service import RunnerService

logger = logging.getLogger("qaclan.routes.requests")
bp = Blueprint("api_requests_bp", __name__)
_svc = RequestService()
_runner_svc = RunnerService()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/api-requests", methods=["GET"])
def list_requests():
    try:
        collection_id = request.args.get("collection_id")
        return jsonify({"ok": True, "requests": _svc.list(_project_id(), collection_id=collection_id)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_requests")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests", methods=["POST"])
def create_request():
    try:
        data = request.get_json(force=True)
        req = _svc.create(_project_id(), data)
        enqueue("api_request", req["id"], "upsert")
        return jsonify({"ok": True, "request": req}), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["GET"])
def get_request(req_id):
    try:
        return jsonify({"ok": True, "request": _svc.get(req_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["PUT"])
def update_request(req_id):
    try:
        data = request.get_json(force=True)
        req = _svc.update(req_id, _project_id(), data)
        enqueue("api_request", req_id, "upsert")
        return jsonify({"ok": True, "request": req})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["PATCH"])
def patch_request(req_id):
    try:
        pid = _project_id()
        existing = _svc.get(req_id, pid)
        patch = request.get_json(force=True) or {}
        merged = {**existing, **patch}
        req = _svc.update(req_id, pid, merged)
        enqueue("api_request", req_id, "upsert")
        return jsonify({"ok": True, "request": req})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("patch_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["DELETE"])
def delete_request(req_id):
    try:
        _svc.delete(req_id, _project_id())
        enqueue("api_request", req_id, "delete")
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/send", methods=["POST"])
def send_request(req_id):
    """Run a single request ad-hoc. Result is NOT stored in api_runs."""
    try:
        data = request.get_json(force=True) or {}
        env_name = data.get("env_name")
        result = _runner_svc.run_request(req_id, _project_id(), env_name=env_name)
        return jsonify({"ok": True, "result": result})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("send_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/response-schema", methods=["POST"])
def set_response_schema(req_id):
    """Save the current/last response shape as the request's frozen
    response_schema baseline (the "Update response schema" action).

    Body may carry an already-inferred `schema` (preferred — the UI passes the
    last send's inferred shape) or a `response_body` (+ optional
    `response_headers`) to infer from.
    """
    try:
        data = request.get_json(force=True) or {}
        schema = _runner_svc.set_response_schema(
            req_id, _project_id(),
            schema=data.get("schema"),
            response_body=data.get("response_body"),
            response_headers=data.get("response_headers"),
        )
        enqueue("api_request", req_id, "upsert")
        return jsonify({"ok": True, "response_schema": schema})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("set_response_schema")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/negatives/generate", methods=["POST"])
def generate_negatives(req_id):
    """Generate (or regenerate) negative cases from the request's shape +
    stored field_constraints. Returns the cases (and a diff on regenerate); the
    UI merges and saves via the normal request update."""
    try:
        data = request.get_json(force=True) or {}
        out = _runner_svc.generate_negatives(req_id, _project_id(), regenerate=bool(data.get("regenerate")))
        return jsonify({"ok": True, **out})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("generate_negatives")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/negatives/plan", methods=["GET", "POST"])
def plan_negatives(req_id):
    """Preview a negative run for the safety gate (case count, mutating methods,
    active environment). No requests are sent."""
    try:
        data = request.get_json(silent=True) or {}
        env_name = data.get("env_name") or request.args.get("env_name")
        return jsonify({"ok": True, "plan": _runner_svc.plan_request_negatives(req_id, _project_id(), env_name=env_name)})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("plan_negatives")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/negatives/run", methods=["POST"])
def run_negatives(req_id):
    """Run the request's negative cases (a dedicated action). Requires
    confirm_destructive when any enabled case uses a mutating verb; otherwise
    responds with needs_confirm and sends nothing."""
    try:
        data = request.get_json(force=True) or {}
        out = _runner_svc.run_negatives(
            req_id, _project_id(),
            env_name=data.get("env_name"),
            confirm_destructive=bool(data.get("confirm_destructive")),
        )
        return jsonify({"ok": out.get("ok", True), **out})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("run_negatives")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/examples", methods=["GET"])
def list_request_examples(req_id):
    try:
        return jsonify({"ok": True, "examples": _svc.list_examples(req_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_request_examples")
        return jsonify({"ok": False, "error": str(e)}), 500
