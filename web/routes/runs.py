import os
import re
import time
import traceback
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id

bp = Blueprint('runs', __name__)


def _require_active_project():
    return get_active_project_id()


def _extract_test_actions(script_path):
    """Extract test action lines from a Playwright codegen script."""
    with open(script_path, "r") as f:
        lines = f.readlines()

    actions = []
    capturing = False
    base_indent = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("page = context.new_page()"):
            capturing = True
            continue

        if capturing and stripped.startswith("page.close()"):
            break

        if capturing:
            if not stripped or stripped.startswith("# ---"):
                continue
            if "_qc_state" in stripped or "context.storage_state" in stripped:
                continue
            if base_indent is None:
                base_indent = len(line) - len(line.lstrip())
            current_indent = len(line) - len(line.lstrip())
            relative_indent = max(0, current_indent - base_indent)
            actions.append(" " * relative_indent + stripped)

    return "\n".join(actions)


def _patch_actions(actions_src):
    """Apply runtime patches: networkidle waits."""
    actions_src = re.sub(
        r'(page\.goto\([^)]+\))',
        r'\1\npage.wait_for_load_state("networkidle")',
        actions_src,
    )
    actions_src = re.sub(
        r'(\.click\(\))',
        r'\1\npage.wait_for_load_state("networkidle")',
        actions_src,
    )
    return actions_src


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
            "sr.started_at, sr.finished_at "
            "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
            "WHERE sr.id = ? AND sr.project_id = ?",
            (run_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404

        run = dict(row)

        # Load script results
        script_rows = conn.execute(
            "SELECT scr.script_id, s.name, scr.status, scr.duration_ms, "
            "scr.console_errors, scr.network_failures, scr.error_message, "
            "scr.order_index, scr.started_at, scr.finished_at "
            "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
            "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
            (run_id,),
        ).fetchall()
        run["scripts"] = [dict(sr) for sr in script_rows]

        return jsonify({"ok": True, "run": run})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/runs', methods=['POST'])
def execute_run():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        suite_id = data.get("suite_id", "").strip()
        env_name = data.get("env_name")
        stop_on_fail = data.get("stop_on_fail", False)

        if not suite_id:
            return jsonify({"ok": False, "error": "suite_id is required"}), 400

        conn = get_conn()

        # 1. Load suite and validate
        suite = conn.execute(
            "SELECT * FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not suite:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404
        if suite["channel"] != "web":
            return jsonify({
                "ok": False,
                "error": f"Suite {suite_id} is a {suite['channel'].upper()} suite, not a WEB suite"
            }), 400

        # 2. Load suite items with scripts (ordered)
        items = conn.execute(
            "SELECT si.order_index, sc.id AS script_id, sc.name AS script_name, sc.file_path "
            "FROM suite_items si JOIN scripts sc ON si.script_id = sc.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        if not items:
            return jsonify({"ok": False, "error": "Suite has no scripts"}), 400

        # 3. Load env vars if env_name provided
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
                "SELECT key, value FROM env_vars WHERE environment_id = ?",
                (env_row["id"],),
            ).fetchall()
            for v in variables:
                env_vars_dict[v["key"]] = v["value"]

        # Inject env vars into current process
        for k, v in env_vars_dict.items():
            os.environ[k] = v

        # 4. Create suite_run record
        run_id = generate_id("run")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at) "
            "VALUES (?, ?, ?, ?, 'web', 'RUNNING', ?, ?)",
            (run_id, suite_id, project_id, environment_id, len(items), now),
        )
        conn.commit()

        total = len(items)
        passed = 0
        failed = 0
        skipped = 0
        stopped = False
        script_results = []
        run_start = time.time()

        # Storage state file for session persistence across runs
        storage_state_path = os.path.join(os.path.expanduser("~/.qaclan"), "storage_state.json")

        # Point Playwright to bundled browsers only when no system browsers exist
        bundled_browsers = os.path.expanduser("~/.qaclan/browsers")
        default_browsers = os.path.expanduser("~/.cache/ms-playwright")
        if (os.path.isdir(bundled_browsers)
                and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                and not os.path.isdir(default_browsers)):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

        # 5. Launch ONE shared browser for the entire suite
        from playwright.sync_api import sync_playwright, expect as pw_expect

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(
                storage_state=storage_state_path if os.path.exists(storage_state_path) else None
            )

            # 6. Loop through scripts
            for item in items:
                srun_id = generate_id("srun")
                script_now = datetime.now(timezone.utc).isoformat()

                if stopped:
                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, 'SKIPPED', ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"], script_now, script_now),
                    )
                    skipped += 1
                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item["script_name"],
                        "status": "SKIPPED",
                        "duration_ms": 0,
                        "error_message": None,
                    })
                    continue

                script_start = time.time()

                try:
                    # Extract and patch test actions
                    actions_src = _extract_test_actions(item["file_path"])
                    actions_src = _patch_actions(actions_src)

                    # Create a new page in the shared context
                    page = context.new_page()
                    page.set_default_timeout(30000)

                    # Execute test actions with page, context, and expect in scope
                    exec(actions_src, {
                        "page": page,
                        "context": context,
                        "expect": pw_expect,
                        "re": re,
                        "os": os,
                    })

                    page.wait_for_timeout(2000)  # Allow JS to persist session to localStorage
                    page.close()

                    duration_ms = int((time.time() - script_start) * 1000)
                    finished_at = datetime.now(timezone.utc).isoformat()

                    status = "PASSED"
                    passed += 1
                    error_msg = None

                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                        "duration_ms, error_message, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"],
                         status, duration_ms, error_msg, script_now, finished_at),
                    )

                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item["script_name"],
                        "status": status,
                        "duration_ms": duration_ms,
                        "error_message": error_msg,
                    })
                except Exception as e:
                    try:
                        page.close()
                    except Exception:
                        pass

                    duration_ms = int((time.time() - script_start) * 1000)
                    finished_at = datetime.now(timezone.utc).isoformat()
                    failed += 1
                    error_msg = traceback.format_exc()
                    if stop_on_fail:
                        stopped = True

                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                        "duration_ms, error_message, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"],
                         duration_ms, error_msg, script_now, finished_at),
                    )

                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item["script_name"],
                        "status": "FAILED",
                        "duration_ms": duration_ms,
                        "error_message": error_msg,
                    })

            # Save storage state for session persistence
            context.storage_state(path=storage_state_path)

            # Close shared browser
            context.close()
            browser.close()

        # Clean up injected env vars
        for k in env_vars_dict:
            os.environ.pop(k, None)

        # 8. Finalize suite_run
        final_status = "PASSED" if failed == 0 and skipped == 0 else "FAILED"
        finished_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE suite_runs SET status = ?, passed = ?, failed = ?, skipped = ?, finished_at = ? "
            "WHERE id = ?",
            (final_status, passed, failed, skipped, finished_at, run_id),
        )

        # 9. Update suite metadata
        conn.execute(
            "UPDATE suites SET last_run_at = ?, last_run_status = ? WHERE id = ?",
            (finished_at, final_status, suite_id),
        )
        conn.execute(
            "UPDATE suites SET first_run_at = ? WHERE id = ? AND first_run_at IS NULL",
            (finished_at, suite_id),
        )
        conn.commit()

        # Sync run to cloud
        from cli.sync import sync_run_to_cloud
        total_duration_ms = int((time.time() - run_start) * 1000)
        sync_run_to_cloud(
            run_id=run_id,
            suite_id=suite_id,
            status=final_status,
            started_at=now,
            completed_at=finished_at,
            duration_ms=total_duration_ms,
            project_id=project_id,
            script_results=[
                {
                    "script_id": sr["script_id"],
                    "script_name": sr["name"],
                    "status": sr["status"].lower(),
                    "duration_ms": sr.get("duration_ms", 0) or 0,
                    "error_output": sr.get("error_message"),
                    "order_index": idx,
                }
                for idx, sr in enumerate(script_results)
            ],
        )

        # 10. Return completed run data
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
        return jsonify({"ok": False, "error": str(e)}), 500
