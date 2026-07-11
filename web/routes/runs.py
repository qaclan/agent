import json
import os
import shutil
import subprocess
import time
import logging
import traceback
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from pathlib import Path

from cli.commands.web.record import DEFAULT_RECORD_RESOLUTION
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, QACLAN_DIR
from cli.runtime import is_frozen_binary, get_default_playwright_browsers_path
from cli.runtime_setup import RUNTIME_DIR
from cli.crypto import decrypt
from cli.script_strategies import get_strategy
from cli.script_strategies._shared import substitute_template_vars

logger = logging.getLogger("qaclan.runs")

bp = Blueprint('runs', __name__)

RUNS_DIR = RUNTIME_DIR / "runs"
SCREENSHOTS_DIR = Path(QACLAN_DIR) / "screenshots"
PER_SCRIPT_TIMEOUT_SEC = 300  # 5 minutes per script before kill


def _require_active_project():
    return get_active_project_id()


def _read_artifacts(path: Path):
    """Read the artifacts JSON a script writes on exit. Missing or malformed
    files degrade gracefully to empty lists — a crashed script may not have
    written anything.

    Returns (console_errors, network_failures, error) — `error` is the
    harness's structured exception dict ({raw_type, raw_message}) or None.
    """
    if not path.exists():
        return [], [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            data.get("console_errors", []) or [],
            data.get("network_failures", []) or [],
            data.get("error") or None,
        )
    except Exception as e:
        logger.warning("Failed to read artifacts at %s: %s", path, e)
        return [], [], None


def _build_error_detail(*, kind, returncode=None, stdout=None, stderr=None,
                        artifacts_error=None, exc=None, has_network_failures=False):
    """Turn a failure into (detail, raw): `detail` is the structured dict for
    the error_detail column, `raw` is the raw blob for error_message. The raw
    blob is NOT embedded in detail — stored once. See error-reporting-plan §2.3.

    kind: "subprocess" | "timeout" | "internal".
    """
    from cli.error_classifier import classify

    if kind == "internal":
        raw = stderr or (traceback.format_exc() if exc else "")
        detail = classify(
            raw_type=type(exc).__name__ if exc else None,
            raw_message=str(exc) if exc else None,
            stderr=raw, kind="internal",
        )
        return detail, raw

    if kind == "timeout":
        raw = stderr or f"Script timed out after {PER_SCRIPT_TIMEOUT_SEC}s"
        detail = classify(kind="timeout", has_network_failures=has_network_failures)
        return detail, raw

    # subprocess: script exited non-zero.
    stderr_txt = (stderr or "").strip()
    stdout_txt = (stdout or "").strip()
    parts = []
    if stderr_txt:
        parts.append(f"[stderr]\n{stderr_txt}")
    if stdout_txt:
        parts.append(f"[stdout]\n{stdout_txt}")
    raw = "\n\n".join(parts) or f"exit code {returncode}"
    # When the harness emitted a structured error, trust it exclusively: the
    # stderr/stdout blob carries rendered source code that fools keyword
    # rules. Pass the blob only as the fallback for the no-artifacts case
    # (compile-fail / timeout). See error-reporting-plan §6.2.
    has_harness_msg = bool((artifacts_error or {}).get("raw_message"))
    detail = classify(
        raw_type=(artifacts_error or {}).get("raw_type"),
        raw_message=(artifacts_error or {}).get("raw_message"),
        stderr=None if has_harness_msg else stderr_txt,
        stdout=None if has_harness_msg else stdout_txt,
        kind="subprocess", returncode=returncode,
        has_network_failures=has_network_failures,
    )
    return detail, raw


@bp.route('/api/runs', methods=['GET'])
def list_runs():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        suite_id = request.args.get("suite_id")

        if suite_id:
            rows = conn.execute(
                "SELECT sr.id, sr.suite_id, su.name AS suite_name, sr.status, "
                "sr.started_at, sr.finished_at, sr.total, sr.passed, sr.failed, sr.skipped "
                "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
                "WHERE sr.project_id = ? AND sr.suite_id = ? "
                "ORDER BY sr.started_at DESC",
                (project_id, suite_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sr.id, sr.suite_id, su.name AS suite_name, sr.status, "
                "sr.started_at, sr.finished_at, sr.total, sr.passed, sr.failed, sr.skipped "
                "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
                "WHERE sr.project_id = ? "
                "ORDER BY sr.started_at DESC",
                (project_id,),
            ).fetchall()

        runs = [dict(r) for r in rows]
        return jsonify({"ok": True, "runs": runs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/runs/<run_id>', methods=['GET'])
def get_run(run_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT sr.id, sr.suite_id, su.name AS suite_name, sr.environment_id, "
            "sr.channel, sr.status, sr.total, sr.passed, sr.failed, sr.skipped, "
            "sr.started_at, sr.finished_at, sr.browser, sr.resolution, sr.headless "
            "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
            "WHERE sr.id = ? AND sr.project_id = ?",
            (run_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404

        run = dict(row)

        script_rows = conn.execute(
            "SELECT scr.script_id, s.name, scr.status, scr.duration_ms, "
            "scr.console_errors, scr.network_failures, scr.error_message, scr.error_detail, "
            "scr.console_log, scr.network_log, scr.screenshot_path, "
            "scr.order_index, scr.started_at, scr.finished_at "
            "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
            "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
            (run_id,),
        ).fetchall()
        # error_detail is stored as a JSON string — parse it so the frontend
        # gets a structured object, not a string.
        run["scripts"] = []
        for sr in script_rows:
            d = dict(sr)
            if d.get("error_detail"):
                try:
                    d["error_detail"] = json.loads(d["error_detail"])
                except (TypeError, ValueError):
                    d["error_detail"] = None
            run["scripts"].append(d)

        return jsonify({"ok": True, "run": run})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/runs/<run_id>/report', methods=['GET'])
def download_report(run_id):
    """Generate and download a self-contained offline HTML report for a run.
    See docs/error-reporting-plan.md (section 4)."""
    from flask import Response
    from cli.report import generate_html_report
    try:
        html_str = generate_html_report(run_id)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.error("download_report: failed for %s: %s", run_id, e, exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    # ?view=1 serves the report inline (open in a browser tab); the default
    # serves it as an attachment (save to disk). The UI fires both at once.
    disposition = "inline" if request.args.get("view") else "attachment"
    return Response(
        html_str,
        mimetype="text/html",
        headers={
            "Content-Disposition": f'{disposition}; filename="qaclan-report-{run_id}.html"'
        },
    )


def _cleanup_run_dir(run_dir):
    """Remove the per-run working directory once data has been persisted to DB.
    Errors are swallowed — a stale run_dir is a disk-space issue, not a
    correctness issue, and the user already has the result they care about."""
    if not run_dir:
        return
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("Failed to cleanup run_dir %s: %s", run_dir, e)


@bp.route('/api/runs', methods=['POST'])
def execute_run():
    run_dir = None
    try:
        project_id = _require_active_project()
        if not project_id:
            logger.warning("execute_run: no active project")
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        suite_id = data.get("suite_id", "").strip()
        env_name = data.get("env_name")
        stop_on_fail = data.get("stop_on_fail", False)
        browser_type = data.get("browser", "chromium")
        resolution = data.get("resolution") or None
        headless = data.get("headless", False)
        # Run-level "Wait limit" — one knob driving both QACLAN_EXPECT_TIMEOUT
        # (assertions) and QACLAN_ACTION_TIMEOUT (clicks/fills/waits). A
        # per-script wait_timeout column can override this inside the loop.
        # See docs/expect-timeout-strategy-plan.md.
        _ALLOWED_WAIT_TIMEOUTS = {5000, 10000, 15000, 30000, 45000, 60000}
        _DEFAULT_WAIT_TIMEOUT = 15000
        # Accept both the new "wait_timeout" key and the legacy "expect_timeout".
        _raw_wait = data.get("wait_timeout", data.get("expect_timeout"))
        run_wait_timeout = _raw_wait if isinstance(_raw_wait, int) and _raw_wait in _ALLOWED_WAIT_TIMEOUTS else _DEFAULT_WAIT_TIMEOUT
        logger.info("execute_run: suite_id=%s env_name=%s stop_on_fail=%s browser=%s resolution=%s headless=%s wait_timeout=%s",
                     suite_id, env_name, stop_on_fail, browser_type, resolution, headless, run_wait_timeout)

        if not suite_id:
            return jsonify({"ok": False, "error": "suite_id is required"}), 400

        conn = get_conn()

        suite = conn.execute(
            "SELECT * FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not suite:
            logger.error("execute_run: suite %s not found in project %s", suite_id, project_id)
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404
        if suite["channel"] != "web":
            return jsonify({
                "ok": False,
                "error": f"Suite {suite_id} is a {suite['channel'].upper()} suite, not a WEB suite"
            }), 400

        items = conn.execute(
            "SELECT si.id AS item_id, si.order_index, si.item_type, "
            "si.script_id, si.api_request_id, "
            "sc.name AS script_name, sc.file_path, sc.language, sc.start_url_key, "
            "sc.start_url_value, sc.var_keys, sc.wait_timeout "
            "FROM suite_items si "
            "LEFT JOIN scripts sc ON si.script_id = sc.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        if not items:
            logger.warning("execute_run: suite %s has no items", suite_id)
            return jsonify({"ok": False, "error": "Suite has no items"}), 400

        logger.info("execute_run: loaded %d scripts for suite %s (%s)", len(items), suite_id, suite["name"])

        # Pre-flight: every language present in the suite must have a working runtime.
        # Only script items have a language; api_request items need no runtime validation.
        from cli import runtime_setup
        languages_in_suite = {item["language"] or "python" for item in items if item["item_type"] == "script"}
        for lang in languages_in_suite:
            try:
                get_strategy(lang).validate_runtime()
            except (ValueError, RuntimeError) as e:
                logger.error("execute_run: runtime check failed for language %s: %s", lang, e)
                if not runtime_setup.runtime_initialized():
                    return jsonify(runtime_setup.runtime_needs_setup_payload(str(e))), 400
                return jsonify({"ok": False, "error": str(e)}), 400

        # Load env vars for substitution. These are passed to subprocesses via
        # the `env` param only — we never mutate os.environ of the Flask process.
        env_vars_dict = {}
        environment_id = None
        if env_name:
            env_name = env_name.strip()
            env_row = conn.execute(
                "SELECT * FROM environments WHERE project_id = ? AND name = ?",
                (project_id, env_name),
            ).fetchone()
            if not env_row:
                return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404
            environment_id = env_row["id"]
            variables = conn.execute(
                "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
                (env_row["id"],),
            ).fetchall()
            for v in variables:
                val = v["value"]
                if v["is_secret"] and val:
                    val = decrypt(val)
                env_vars_dict[v["key"]] = val
            logger.info("execute_run: loaded %d env vars from environment '%s'", len(env_vars_dict), env_name)

        run_id = generate_id("run")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at, browser, resolution, headless) "
            "VALUES (?, ?, ?, ?, 'web', 'RUNNING', ?, ?, ?, ?, ?)",
            (run_id, suite_id, project_id, environment_id, len(items), now, browser_type, resolution, 1 if headless else 0),
        )
        conn.commit()
        logger.info("execute_run: created run %s at %s", run_id, now)

        # Per-run working directory: holds the rendered scripts, the shared
        # storage-state JSON, and per-script artifact files. 0o700 so cookies
        # and decrypted env values aren't world-readable on multi-user hosts.
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        state_file = run_dir / "state.json"  # created on first script's exit

        # Per-language, per-run setup. _test strategies write a single shared
        # playwright.config.js here so each script doesn't rewrite it.
        for lang in languages_in_suite:
            try:
                get_strategy(lang).setup_run_dir(str(run_dir))
            except Exception as e:
                logger.warning("execute_run: setup_run_dir failed for language %s: %s", lang, e)

        total = len(items)
        passed = 0
        failed = 0
        skipped = 0
        stopped = False
        script_results = []
        run_start = time.time()

        # In Nuitka binary builds the bundled Node driver segfaults; set
        # PLAYWRIGHT_BROWSERS_PATH so subprocesses find system-installed browsers.
        default_browsers = get_default_playwright_browsers_path()
        is_frozen = is_frozen_binary()
        logger.info("execute_run: is_frozen=%s", is_frozen)
        pw_browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        # Prefer isolated runtime browsers dir.
        rt_browsers = runtime_setup.browsers_path_if_present()
        if not pw_browsers_path and rt_browsers is not None:
            pw_browsers_path = str(rt_browsers)
            logger.info("execute_run: using PLAYWRIGHT_BROWSERS_PATH=%s (runtime)", pw_browsers_path)
        elif is_frozen and not pw_browsers_path and os.path.isdir(default_browsers):
            pw_browsers_path = default_browsers
            logger.info("execute_run: using PLAYWRIGHT_BROWSERS_PATH=%s (binary-mode default)", pw_browsers_path)

        for idx, item in enumerate(items):
            srun_id = generate_id("srun")
            script_now = datetime.now(timezone.utc).isoformat()
            language = item["language"] or "python"

            if stopped:
                logger.info("execute_run: [%d/%d] %s — SKIPPED (stop-on-fail)", idx + 1, total, item.get("script_name") or item.get("api_request_id"))
                if item["item_type"] == "api_request":
                    skipped += 1
                    script_results.append({
                        "item_type": "api_request",
                        "api_request_id": item["api_request_id"],
                        "name": item.get("api_request_id"),
                        "status": "SKIPPED",
                        "duration_ms": 0,
                        "error_message": None,
                    })
                else:
                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, 'SKIPPED', ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"], script_now, script_now),
                    )
                    skipped += 1
                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item.get("script_name") or item.get("api_request_id"),
                        "status": "SKIPPED",
                        "duration_ms": 0,
                        "error_message": None,
                    })
                continue

            # --- API request item branch ---
            if item["item_type"] == "api_request":
                api_req_id = item["api_request_id"]
                api_start = time.time()

                try:
                    from cli.api_runner import run_api_request
                    from web.api.repositories.api_run_repo import ApiRunRepo

                    # Load the api_request row
                    api_req_row = conn.execute(
                        "SELECT * FROM api_requests WHERE id = ?", (api_req_id,)
                    ).fetchone()
                    if not api_req_row:
                        raise LookupError(f"api_request {api_req_id} not found")

                    import json as _json
                    api_req = dict(api_req_row)
                    for _key in ("headers", "params", "assertions"):
                        if isinstance(api_req.get(_key), str):
                            try:
                                api_req[_key] = _json.loads(api_req[_key])
                            except (ValueError, TypeError):
                                api_req[_key] = []
                    if isinstance(api_req.get("auth_config"), str):
                        try:
                            api_req["auth_config"] = _json.loads(api_req["auth_config"])
                        except (ValueError, TypeError):
                            api_req["auth_config"] = {}

                    # Load state.json and extract qaclan_vars
                    state_dict: dict = {}
                    if state_file.exists():
                        try:
                            state_dict = _json.loads(state_file.read_text(encoding="utf-8"))
                        except (ValueError, OSError):
                            state_dict = {}

                    api_result = run_api_request(
                        api_req, env_vars_dict, state_dict, state_path=str(state_file)
                    )

                    # Merge state_updates back into state.json qaclan_vars
                    state_updates = api_result.get("state_updates", {})
                    if state_updates:
                        state_dict.setdefault("qaclan_vars", {}).update(state_updates)
                        try:
                            state_file.write_text(_json.dumps(state_dict), encoding="utf-8")
                        except OSError as _ose:
                            logger.warning("execute_run: could not write state.json: %s", _ose)

                    # Persist api_run row
                    ApiRunRepo().create(run_id, api_req_id, item["order_index"], api_result)

                    api_duration_ms = int((time.time() - api_start) * 1000)
                    api_status = api_result.get("status", "ERROR")
                    if api_status == "PASSED":
                        passed += 1
                    else:
                        failed += 1
                        if stop_on_fail:
                            stopped = True

                    script_results.append({
                        "item_type": "api_request",
                        "api_request_id": api_req_id,
                        "name": api_req.get("name", api_req_id),
                        "status": api_status,
                        "duration_ms": api_duration_ms,
                        "status_code": api_result.get("status_code"),
                        "error_message": api_result.get("error_message"),
                        "assertion_results": api_result.get("assertion_results", []),
                    })
                    logger.info("execute_run: [%d/%d] API '%s' — %s (%dms)",
                                idx + 1, total, api_req.get("name"), api_status, api_duration_ms)

                except Exception as _api_exc:
                    failed += 1
                    if stop_on_fail:
                        stopped = True
                    err_msg = str(_api_exc)
                    logger.error("execute_run: [%d/%d] API item error: %s", idx + 1, total, err_msg)
                    script_results.append({
                        "item_type": "api_request",
                        "api_request_id": api_req_id,
                        "name": api_req_id,
                        "status": "ERROR",
                        "duration_ms": int((time.time() - api_start) * 1000),
                        "error_message": err_msg,
                    })
                continue  # skip rest of script-item logic
            # --- End API request item branch ---

            logger.info("execute_run: [%d/%d] running '%s' (%s, %s)...",
                        idx + 1, total, item["script_name"], item["script_id"], language)
            script_start = time.time()
            screenshot_path = SCREENSHOTS_DIR / f"{srun_id}.png"
            artifacts_path = run_dir / f"{srun_id}.artifacts.json"

            try:
                strategy = get_strategy(language)
                # File at file_path is the single source of truth for script
                # body. The DB source column is legacy and may be stale or a
                # sentinel ("PULLED", "WEB_CREATED", "CLI_RECORDED").
                script_path = item["file_path"]
                if not script_path or not os.path.exists(script_path):
                    raise FileNotFoundError(f"Script file not found: {script_path}")
                source = Path(script_path).read_text(encoding="utf-8")

                # Resolve {{KEY}} placeholders against the selected env (with
                # recorded start-URL fallback). Values are escaped for the
                # target language so a "-containing value can't break out of
                # the string literal and inject code.
                try:
                    script_var_keys = json.loads(item["var_keys"] or "[]")
                except (TypeError, ValueError) as e:
                    print("execute_run: %s — invalid var_keys: %s -  error: %s", item["script_name"], item["var_keys"], e)
                    script_var_keys = []
                if script_var_keys:
                    source, subs_warnings = substitute_template_vars(
                        source, script_var_keys, env_vars_dict,
                        item["start_url_key"], item["start_url_value"],
                        escape_fn=strategy.escape_for_literal,
                    )
                    for w in subs_warnings:
                        logger.warning("execute_run: %s — %s", item["script_name"], w)

                # Write the rendered, substituted script into the run directory
                # so the subprocess executes a known file with no {{KEY}} left.
                rendered_path = run_dir / f"{srun_id}{strategy.file_extension}"
                rendered_path.write_text(source, encoding="utf-8")
                try:
                    os.chmod(rendered_path, 0o600)
                except OSError:
                    pass

                # Build the subprocess env from scratch — copy the parent env,
                # overlay env_vars_dict (so scripts can read their own secrets
                # via os.environ inside the child), then the QACLAN_* contract
                # vars. Secrets never land in the parent's os.environ.
                child_env = os.environ.copy()
                child_env.update(env_vars_dict)
                child_env["QACLAN_STORAGE_STATE"] = str(state_file)
                child_env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
                child_env["QACLAN_SCREENSHOT_PATH"] = str(screenshot_path)
                child_env["QACLAN_BROWSER"] = browser_type
                child_env["QACLAN_HEADLESS"] = "1" if headless else "0"
                child_env["QACLAN_VIEWPORT"] = resolution or DEFAULT_RECORD_RESOLUTION
                # Resolve the effective wait limit for THIS script:
                #   script.wait_timeout  >  run-level pick  >  default.
                # One value drives both the expect (assertion) and action
                # (click/fill/wait) timeouts — see expect-timeout-strategy-plan.md.
                _script_wt = item["wait_timeout"]
                if isinstance(_script_wt, int) and _script_wt in _ALLOWED_WAIT_TIMEOUTS:
                    effective_wait_timeout = _script_wt
                else:
                    effective_wait_timeout = run_wait_timeout
                child_env["QACLAN_EXPECT_TIMEOUT"] = str(effective_wait_timeout)
                child_env["QACLAN_ACTION_TIMEOUT"] = str(effective_wait_timeout)
                # Inject qaclan_vars from state.json so scripts can read them as QACLAN_STATE_* env vars
                if state_file.exists():
                    try:
                        import json as _sjson
                        _state = _sjson.loads(state_file.read_text(encoding="utf-8"))
                        for _vk, _vv in _state.get("qaclan_vars", {}).items():
                            child_env[f"QACLAN_STATE_{_vk}"] = str(_vv)
                    except (ValueError, OSError):
                        pass
                if pw_browsers_path:
                    child_env["PLAYWRIGHT_BROWSERS_PATH"] = pw_browsers_path

                child_env.update(strategy.extra_env())
                cmd = strategy.build_run_command(str(rendered_path))
                logger.debug("execute_run: spawning %s", cmd)

                proc = subprocess.run(
                    cmd,
                    env=child_env,
                    capture_output=True,
                    text=True,
                    timeout=PER_SCRIPT_TIMEOUT_SEC,
                )

                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                console_errors, network_failures, artifacts_error = _read_artifacts(artifacts_path)

                error_detail = None
                if proc.returncode == 0:
                    status = "PASSED"
                    error_msg = None
                    passed += 1
                    saved_screenshot = None
                    logger.info("execute_run: [%d/%d] %s — PASSED (%dms) console_errors=%d network_failures=%d",
                                idx + 1, total, item["script_name"], duration_ms,
                                len(console_errors), len(network_failures))
                else:
                    status = "FAILED"
                    error_detail, error_msg = _build_error_detail(
                        kind="subprocess", returncode=proc.returncode,
                        stdout=proc.stdout, stderr=proc.stderr,
                        artifacts_error=artifacts_error,
                        has_network_failures=bool(network_failures),
                    )
                    failed += 1
                    saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None
                    logger.error("execute_run: [%d/%d] %s — FAILED (%dms, exit=%d) [%s]: %s",
                                 idx + 1, total, item["script_name"], duration_ms, proc.returncode,
                                 error_detail["category"], error_msg[:1000])
                    if stop_on_fail:
                        stopped = True
                        logger.info("execute_run: stop-on-fail triggered, remaining scripts will be skipped")

                error_detail_json = json.dumps(error_detail) if error_detail else None
                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, error_detail, console_errors, network_failures, "
                    "console_log, network_log, screenshot_path, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"], status,
                     duration_ms, error_msg, error_detail_json,
                     len(console_errors), len(network_failures),
                     json.dumps(console_errors) if console_errors else None,
                     json.dumps(network_failures) if network_failures else None,
                     saved_screenshot, script_now, finished_at),
                )

                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "error_detail": error_detail,
                    "screenshot_path": saved_screenshot,
                    "console_errors": len(console_errors),
                    "network_failures": len(network_failures),
                    "console_log": json.dumps(console_errors) if console_errors else None,
                    "network_log": json.dumps(network_failures) if network_failures else None,
                })

            except subprocess.TimeoutExpired:
                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                failed += 1
                saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None
                logger.error("execute_run: [%d/%d] %s — TIMEOUT (%dms)",
                             idx + 1, total, item["script_name"], duration_ms)
                if stop_on_fail:
                    stopped = True
                # Partial console/network data may still exist from the killed
                # subprocess; the harness `error` almost never does.
                console_errors, network_failures, artifacts_error = _read_artifacts(artifacts_path)
                error_detail, error_msg = _build_error_detail(
                    kind="timeout", has_network_failures=bool(network_failures),
                )
                error_detail_json = json.dumps(error_detail)
                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, error_detail, console_errors, network_failures, "
                    "console_log, network_log, screenshot_path, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"],
                     duration_ms, error_msg, error_detail_json,
                     len(console_errors), len(network_failures),
                     json.dumps(console_errors) if console_errors else None,
                     json.dumps(network_failures) if network_failures else None,
                     saved_screenshot, script_now, finished_at),
                )
                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": "FAILED",
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "error_detail": error_detail,
                    "screenshot_path": saved_screenshot,
                    "console_errors": len(console_errors),
                    "network_failures": len(network_failures),
                    "console_log": json.dumps(console_errors) if console_errors else None,
                    "network_log": json.dumps(network_failures) if network_failures else None,
                })

            except Exception as e:
                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                failed += 1
                error_detail, error_msg = _build_error_detail(kind="internal", exc=e)
                error_detail_json = json.dumps(error_detail)
                logger.error("execute_run: [%d/%d] %s — INTERNAL ERROR (%dms) [%s]: %s",
                             idx + 1, total, item["script_name"], duration_ms,
                             error_detail["category"], e)
                if stop_on_fail:
                    stopped = True
                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, error_detail, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"],
                     duration_ms, error_msg, error_detail_json, script_now, finished_at),
                )
                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": "FAILED",
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "error_detail": error_detail,
                })

        # Ensure the env-vars dict is released promptly so decrypted secrets
        # don't linger in the Flask worker's memory.
        env_vars_dict.clear()

        final_status = "PASSED" if failed == 0 and skipped == 0 else "FAILED"
        finished_at = datetime.now(timezone.utc).isoformat()
        total_duration_ms = int((time.time() - run_start) * 1000)
        logger.info("execute_run: run %s finished — %s (passed=%d failed=%d skipped=%d duration=%dms)",
                     run_id, final_status, passed, failed, skipped, total_duration_ms)
        conn.execute(
            "UPDATE suite_runs SET status = ?, passed = ?, failed = ?, skipped = ?, finished_at = ? "
            "WHERE id = ?",
            (final_status, passed, failed, skipped, finished_at, run_id),
        )

        conn.execute(
            "UPDATE suites SET last_run_at = ?, last_run_status = ? WHERE id = ?",
            (finished_at, final_status, suite_id),
        )
        conn.execute(
            "UPDATE suites SET first_run_at = ? WHERE id = ? AND first_run_at IS NULL",
            (finished_at, suite_id),
        )
        conn.commit()

        # Queue run for cloud sync (payload built at drain time from DB)
        logger.debug("execute_run: enqueueing run %s for cloud sync", run_id)
        from cli.sync_queue import enqueue
        enqueue("run", run_id, "upsert")

        return jsonify({
            "ok": True,
            "run": {
                "id": run_id,
                "suite_id": suite_id,
                "suite_name": suite["name"],
                "status": final_status,
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "started_at": now,
                "finished_at": finished_at,
                "scripts": script_results,
            },
        })
    except Exception as e:
        logger.error("execute_run: top-level exception: %s", e, exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        # All console_errors / network_failures / screenshots already in DB
        # or SCREENSHOTS_DIR. Run_dir contents (rendered scripts, state.json,
        # *.artifacts.json, playwright.config.js) are disposable. Drop the
        # directory regardless of success/failure path.
        _cleanup_run_dir(run_dir)
        # pass
