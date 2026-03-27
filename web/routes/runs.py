import os
import re
import subprocess
import time
import tempfile
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id

bp = Blueprint('runs', __name__)


def _require_active_project():
    return get_active_project_id()


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

        # 5. Create temp storage state file
        storage_state_file = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, prefix="qaclan_state_"
        )
        storage_state_path = storage_state_file.name
        storage_state_file.close()
        os.unlink(storage_state_path)
        env_vars_dict["QACLAN_STORAGE_STATE"] = storage_state_path

        # 6. Loop through scripts
        for item in items:
            srun_id = generate_id("srun")
            script_now = datetime.now(timezone.utc).isoformat()

            if stopped:
                # Mark remaining as SKIPPED
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
            env = os.environ.copy()
            env.update(env_vars_dict)

            try:
                # Read script and patch headless=False → headless=True for execution
                with open(item["file_path"], "r") as _sf:
                    _script_src = _sf.read()
                # _script_src = re.sub(r'headless\s*=\s*False', 'headless=True', _script_src)
                # Set default timeout to 30s and wait for full page load after navigations and clicks
                _script_src = re.sub(
                    r'(page\s*=\s*context\.new_page\(\))',
                    r'\1\n    page.set_default_timeout(30000)',
                    _script_src,
                )
                _script_src = re.sub(
                    r'(page\.goto\([^)]+\))',
                    r'\1\n    page.wait_for_load_state("networkidle")',
                    _script_src,
                )
                _script_src = re.sub(
                    r'(\.click\(\))',
                    r'\1\n    page.wait_for_load_state("networkidle")',
                    _script_src,
                )
                _tmp_script = tempfile.NamedTemporaryFile(suffix=".py", delete=False, prefix="qaclan_run_")
                _tmp_script.write(_script_src.encode())
                _tmp_script.close()

                result = subprocess.run(
                    ["python", _tmp_script.name],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                os.unlink(_tmp_script.name)
                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()

                if result.returncode == 0:
                    status = "PASSED"
                    passed += 1
                    error_msg = None
                else:
                    status = "FAILED"
                    failed += 1
                    error_msg = (
                        result.stderr.strip()
                        if result.stderr.strip()
                        else "Non-zero exit code"
                    )
                    if stop_on_fail:
                        stopped = True

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
                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                failed += 1
                error_msg = str(e)
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

        # 7. Clean up storage state file
        if os.path.exists(storage_state_path):
            os.unlink(storage_state_path)

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
