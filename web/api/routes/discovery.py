from __future__ import annotations
import json
import logging
import os
import threading
import time
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
_SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours — long enough a legit in-progress recording is never mistaken for abandoned


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
            collection_name = request.form.get("collection_name") or None
            result = _svc.import_openapi(pid, spec, collection_name=collection_name)
        else:
            data = request.get_json(force=True) or {}
            url = data.get("url", "")
            if not url:
                return jsonify({"ok": False, "error": "Provide 'url' or upload a file"}), 400
            collection_name = data.get("collection_name") or None
            result = _svc.import_openapi(pid, url, collection_name=collection_name)
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
        collection_name = request.form.get("collection_name") or None
        result = _svc.import_postman(pid, collection_json, collection_name=collection_name)
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
        collection_name = request.form.get("collection_name") or None
        result = _svc.import_bruno(pid, bru_files, collection_name=collection_name)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_bruno")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/save-requests", methods=["POST"])
def save_requests():
    """Save pre-parsed request objects directly (no re-parsing). Body: {requests, collection_name, include_in_docs}."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        requests_list = data.get("requests", [])
        collection_name = data.get("collection_name", "Recorded APIs")
        include_in_docs = int(data.get("include_in_docs", 1))
        if not requests_list:
            return jsonify({"ok": False, "error": "No requests provided"}), 400
        # Stamp include_in_docs on each request
        for r in requests_list:
            r['include_in_docs'] = include_in_docs
        from web.api.services.discovery_service import _save_requests
        from web.api.repositories.collection_repo import CollectionRepo
        col = CollectionRepo().create(pid, collection_name)
        saved = _save_requests(pid, requests_list, collection_id=col["id"])
        logger.info("save_requests: saved %d to collection %s", saved, col["id"])
        return jsonify({"ok": True, "imported": saved, "collection_id": col["id"]})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("save_requests")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/har/preview", methods=["POST"])
def discover_har_preview():
    """Parse HAR file and return request list without saving."""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        har_json = json.loads(f.read().decode("utf-8"))
        from cli.api_discovery.har_parser import parse_har
        requests_list = parse_har(har_json)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_har_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/openapi/preview", methods=["POST"])
def discover_openapi_preview():
    """Parse OpenAPI spec (file or URL) and return request list without saving."""
    try:
        from cli.api_discovery.openapi_parser import parse_openapi
        if request.files.get("file"):
            f = request.files["file"]
            raw = f.read().decode("utf-8")
            if f.filename.endswith(".yaml") or f.filename.endswith(".yml"):
                import yaml
                spec = yaml.safe_load(raw)
            else:
                spec = json.loads(raw)
        else:
            data = request.get_json(force=True) or {}
            url = data.get("url", "")
            if not url:
                return jsonify({"ok": False, "error": "Provide 'url' or upload a file"}), 400
            import httpx
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                spec = resp.json()
            else:
                import yaml
                spec = yaml.safe_load(resp.text)
        requests_list = parse_openapi(spec)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_openapi_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/postman/preview", methods=["POST"])
def discover_postman_preview():
    """Parse Postman collection file and return request list without saving."""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        collection_json = json.loads(f.read().decode("utf-8"))
        from cli.api_discovery.postman_parser import parse_postman
        requests_list = parse_postman(collection_json)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_postman_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/bruno/preview", methods=["POST"])
def discover_bruno_preview():
    """Parse .bru files and return request list without saving."""
    try:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "error": "No files uploaded (field: 'files')"}), 400
        from cli.api_discovery.bruno_parser import parse_bruno
        requests_list = []
        for f in files:
            parsed = parse_bruno(f.read().decode("utf-8"))
            for req in parsed:
                if req.get("name") in ("Imported Request", "", None):
                    req["name"] = f.filename.replace(".bru", "")
            requests_list.extend(parsed)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_bruno_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/curl/preview", methods=["POST"])
def discover_curl_preview():
    """Parse one or more pasted curl commands and return request list without saving."""
    try:
        data = request.get_json(force=True) or {}
        curl_text = data.get("curl", "")
        if not curl_text.strip():
            return jsonify({"ok": False, "error": "No curl command provided"}), 400
        from cli.api_discovery.curl_parser import parse_curl
        requests_list = parse_curl(curl_text)
        if not requests_list:
            return jsonify({"ok": False, "error": "Could not parse any curl command from the input"}), 400
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_curl_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


def _terminate_recorder(session: dict) -> None:
    """Stop the recorder browser process if still running. Safe to call on
    an already-dead proc. Must run before reading its HAR file so the
    capture is fully flushed (ctx.close() in the harness writes the HAR)."""
    import subprocess, sys
    proc = session.get("proc")
    stop_file = session.get("stop_file", "")
    if not proc:
        return
    try:
        if sys.platform == "win32" and stop_file:
            try:
                open(stop_file, "w").close()
            except OSError:
                proc.terminate()  # sentinel creation failed — fall back to SIGTERM
        else:
            proc.terminate()
        proc.wait(timeout=8 if sys.platform == "win32" else 5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()  # reap zombie — must follow kill()
    finally:
        if stop_file and os.path.exists(stop_file):
            try:
                os.unlink(stop_file)
            except OSError:
                pass


def _cleanup_session_dirs(session: dict) -> None:
    """Remove a session's capture/harness temp directories, if present."""
    import shutil
    for d in (session.get("capture_dir"), session.get("harness_dir")):
        if d and os.path.exists(d):
            try:
                shutil.rmtree(d)
            except Exception:
                pass


def _reap_stale_sessions() -> None:
    """Pop any session older than _SESSION_TTL_SECONDS out of _recording_sessions.
    The scan+pop is synchronous and lock-protected but does no I/O, so it never
    adds meaningful latency to the record_start/record_status call that triggers
    it — even with many stale entries. The slow part (killing the recorder
    process, removing its directories) runs on a throwaway thread so the
    triggering request is never blocked on it. Exists because a client that
    abandons a recording (closed tab, dropped connection) without ever calling
    /record/stop would otherwise leak its capture_dir/harness_dir forever —
    /record/status is deliberately read-only and never tears sessions down."""
    now = time.time()
    stale = []
    with _sessions_lock:
        for session_id in list(_recording_sessions.keys()):
            session = _recording_sessions[session_id]
            if now - session.get("created_at", now) > _SESSION_TTL_SECONDS:
                stale.append(_recording_sessions.pop(session_id))

    if not stale:
        return

    logger.info("_reap_stale_sessions: reaping %d abandoned recording session(s)", len(stale))

    def _teardown_batch():
        for session in stale:
            _terminate_recorder(session)
            _cleanup_session_dirs(session)

    threading.Thread(target=_teardown_batch, daemon=True).start()


@bp.route("/api/discover/record/start", methods=["POST"])
def record_start():
    """Launch a Playwright browser in record mode, capture XHR traffic."""
    try:
        _reap_stale_sessions()
        session_id = str(uuid.uuid4())
        data = request.get_json(force=True) or {}
        url = data.get("url", "about:blank")

        import shutil, tempfile, os
        if not url or not url.startswith(("http://", "https://")):
            return jsonify({"ok": False, "error": "url must start with http:// or https://"}), 400

        from cli import runtime_setup as rs
        if not rs.runtime_initialized():
            return jsonify(rs.runtime_needs_setup_payload("Runtime not initialized — run qaclan setup --runtime-only")), 400

        capture_dir = tempfile.mkdtemp(prefix="qaclan_record_")
        har_file = os.path.join(capture_dir, "capture.har")

        from web.api.services.discovery_service import DiscoveryService
        try:
            proc, stop_file, harness_dir = DiscoveryService().launch_recorder(url, har_file)
        except Exception:
            shutil.rmtree(capture_dir, ignore_errors=True)
            raise

        with _sessions_lock:
            _recording_sessions[session_id] = {
                "status": "recording",
                "proc": proc,
                "stop_file": stop_file,
                "harness_dir": harness_dir,
                "capture_dir": capture_dir,
                "har_file": har_file,
                "created_at": time.time(),
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
    session = None
    try:
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id", "")
        with _sessions_lock:
            session = _recording_sessions.pop(session_id, None)

        if not session:
            return jsonify({"ok": False, "error": f"Session {session_id} not found"}), 404

        _terminate_recorder(session)

        har_file = session.get("har_file", "")
        requests_list = []
        if har_file and os.path.exists(har_file):
            try:
                with open(har_file) as hf:
                    har_json = json.load(hf)
                from cli.api_discovery.har_parser import parse_har, merge_multipart_postdata
                sidecar_file = har_file + ".multipart.json"
                if os.path.exists(sidecar_file):
                    try:
                        with open(sidecar_file) as sf:
                            merge_multipart_postdata(har_json, json.load(sf))
                    except Exception as e:
                        logger.warning("record_stop: multipart sidecar merge failed: %s", e)
                requests_list = parse_har(har_json)
            except Exception as e:
                logger.warning("record_stop: HAR parse failed (partial capture?): %s", e)

        return jsonify({"ok": True, "requests": requests_list, "count": len(requests_list)})

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("record_stop")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        if session:
            _cleanup_session_dirs(session)


@bp.route("/api/discover/record/status", methods=["GET"])
def record_status():
    """Poll recording session status. Read-only — does not tear down the
    session even once the browser process has exited, since /record/stop
    still needs capture_dir/har_file intact to parse the HAR afterward.
    (Stale/abandoned sessions past the TTL are reaped as a side effect of
    this call, via _reap_stale_sessions — that's a different case from a
    live session's process having exited.)"""
    _reap_stale_sessions()
    session_id = request.args.get("session_id", "")
    with _sessions_lock:
        session = _recording_sessions.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "Session not found"}), 404
    proc = session.get("proc")
    alive = proc is not None and proc.poll() is None
    return jsonify({"ok": True, "status": "recording" if alive else "stopped", "session_id": session_id})
