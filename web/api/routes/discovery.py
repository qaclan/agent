from __future__ import annotations
import json
import logging
import threading
import uuid
from flask import Blueprint, request, jsonify
from cli.config import get_active_project_id
from web.api.services.discovery_service import DiscoveryService

logger = logging.getLogger("qaclan.routes.discovery")
bp = Blueprint("api_discovery", __name__)
_svc = DiscoveryService()

# In-memory store for recording sessions: {session_id: {"status": "recording"|"stopped", "requests": [], "proc": proc}}
_recording_sessions: dict = {}
_sessions_lock = threading.Lock()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/discover/har", methods=["POST"])
def discover_har():
    """Multipart file upload. Field name: 'file'. Optional form field: collection_name."""
    try:
        pid = _project_id()
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        har_json = json.loads(f.read().decode("utf-8"))
        collection_name = request.form.get("collection_name") or f.filename.replace(".har", "")
        result = _svc.import_har(pid, har_json, collection_name=collection_name)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_har")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/openapi", methods=["POST"])
def discover_openapi():
    """JSON body {url: ...} OR multipart file upload (field: 'file')."""
    try:
        pid = _project_id()
        if request.files.get("file"):
            f = request.files["file"]
            raw = f.read().decode("utf-8")
            if f.filename.endswith(".yaml") or f.filename.endswith(".yml"):
                import yaml
                spec = yaml.safe_load(raw)
            else:
                spec = json.loads(raw)
            result = _svc.import_openapi(pid, spec)
        else:
            data = request.get_json(force=True) or {}
            url = data.get("url", "")
            if not url:
                return jsonify({"ok": False, "error": "Provide 'url' or upload a file"}), 400
            result = _svc.import_openapi(pid, url)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_openapi")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/postman", methods=["POST"])
def discover_postman():
    """Multipart file upload. Field name: 'file'."""
    try:
        pid = _project_id()
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        collection_json = json.loads(f.read().decode("utf-8"))
        result = _svc.import_postman(pid, collection_json)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_postman")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/bruno", methods=["POST"])
def discover_bruno():
    """Multipart file upload of one or more .bru files. Field name: 'files'."""
    try:
        pid = _project_id()
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "error": "No files uploaded (field: 'files')"}), 400
        bru_files = []
        for f in files:
            bru_files.append({"name": f.filename, "content": f.read().decode("utf-8")})
        result = _svc.import_bruno(pid, bru_files)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_bruno")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/record/start", methods=["POST"])
def record_start():
    """Launch a Playwright browser in record mode, capture XHR traffic."""
    try:
        session_id = str(uuid.uuid4())
        data = request.get_json(force=True) or {}
        url = data.get("url", "about:blank")

        import tempfile, os
        capture_dir = tempfile.mkdtemp(prefix="qaclan_record_")
        har_file = os.path.join(capture_dir, "capture.har")

        from web.api.services.discovery_service import DiscoveryService
        proc = DiscoveryService().launch_recorder(url, har_file)

        with _sessions_lock:
            _recording_sessions[session_id] = {
                "status": "recording",
                "proc": proc,
                "capture_dir": capture_dir,
                "har_file": har_file,
            }

        logger.info("record_start: session %s launched (pid %d)", session_id, proc.pid)
        return jsonify({"ok": True, "session_id": session_id})

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("record_start")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/record/stop", methods=["POST"])
def record_stop():
    """Stop recording session, parse captured HAR, return request list."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id", "")
        with _sessions_lock:
            session = _recording_sessions.pop(session_id, None)

        if not session:
            return jsonify({"ok": False, "error": f"Session {session_id} not found"}), 404

        proc = session.get("proc")
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

        import time
        time.sleep(1)  # Give Playwright time to flush HAR

        har_file = session.get("har_file", "")
        requests_list = []
        if har_file and __import__("os").path.exists(har_file):
            with open(har_file) as hf:
                har_json = json.load(hf)
            from cli.api_discovery.har_parser import parse_har
            requests_list = parse_har(har_json)

        return jsonify({"ok": True, "requests": requests_list, "count": len(requests_list)})

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("record_stop")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/record/status", methods=["GET"])
def record_status():
    """Poll recording session status and current capture count."""
    session_id = request.args.get("session_id", "")
    with _sessions_lock:
        session = _recording_sessions.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "Session not found"}), 404
    proc = session.get("proc")
    alive = proc is not None and proc.poll() is None
    return jsonify({"ok": True, "status": "recording" if alive else "stopped", "session_id": session_id})
