"""Offline-tolerant sync queue.

Every local mutation enqueues a (entity_type, entity_id, op) reference.
A background daemon drains the queue by re-reading current DB state and
calling the existing cli/sync.py helpers. Dedup via UNIQUE constraint
coalesces repeated edits while offline."""

import atexit
import logging
import threading
import time
from datetime import datetime, timezone

import requests

from cli.config import get_auth_key, get_server_url

logger = logging.getLogger(__name__)


ENTITY_ORDER = (
    "project",
    "feature",
    "suite",
    "script",
    "environment",
    "env_vars",
    "suite_items",
    "run",
)

_wake = threading.Event()
_worker_started = False
_lock = threading.Lock()

IDLE_SLEEP = 30
OFFLINE_BACKOFFS = (30, 60, 300, 900)
BATCH_SIZE = 50
ONLINE_PROBE_TIMEOUT = 3


def enqueue(entity_type, entity_id, op):
    """Record a mutation to sync later. Deduplicates via UNIQUE constraint.
    If op='delete', supersede any pending 'upsert' for the same entity."""
    from cli.db import get_conn
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    if op == "delete":
        conn.execute(
            "DELETE FROM sync_queue WHERE entity_type = ? AND entity_id = ? AND op = 'upsert'",
            (entity_type, entity_id),
        )
    conn.execute(
        "INSERT OR IGNORE INTO sync_queue (entity_type, entity_id, op, created_at) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, op, now),
    )
    conn.commit()
    _wake.set()


def queue_depth():
    from cli.db import get_conn
    row = get_conn().execute("SELECT COUNT(*) AS n FROM sync_queue").fetchone()
    return row["n"] if row else 0


def _is_online():
    """Cheap reachability probe. Returns True if the server responded at all."""
    key = get_auth_key()
    if not key:
        return False
    try:
        r = requests.get(
            f"{get_server_url()}/api/sync/status",
            headers={"Authorization": f"Bearer {key}"},
            timeout=ONLINE_PROBE_TIMEOUT,
        )
        return r.status_code < 500
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False
    except Exception:
        return True  # something else — let the real call fail and count as attempt


def _fetch_batch(conn, limit):
    """Pull up to `limit` queue rows in dependency order (upserts first, deletes last)."""
    order_cases = " ".join(
        f"WHEN '{t}' THEN {i}" for i, t in enumerate(ENTITY_ORDER)
    )
    sql = f"""
        SELECT id, entity_type, entity_id, op, attempts
        FROM sync_queue
        ORDER BY
            CASE op WHEN 'upsert' THEN 0 ELSE 1 END,
            CASE entity_type {order_cases} ELSE 99 END,
            id
        LIMIT ?
    """
    return conn.execute(sql, (limit,)).fetchall()


def _dispatch(row):
    """Run the actual HTTP sync for one queue row. Raises on failure."""
    from cli import sync
    from cli.db import get_conn

    et, eid, op = row["entity_type"], row["entity_id"], row["op"]
    conn = get_conn()

    with sync.strict_mode():
        if op == "delete":
            {
                "project": sync.delete_project_from_cloud,
                "feature": sync.delete_feature_from_cloud,
                "suite": sync.delete_suite_from_cloud,
                "script": sync.delete_script_from_cloud,
                "environment": sync.delete_environment_from_cloud,
            }[et](eid)
            return

        if et == "project":
            r = conn.execute("SELECT name FROM projects WHERE id = ?", (eid,)).fetchone()
            if r:
                sync.sync_project_to_cloud(eid, r["name"])
        elif et == "feature":
            r = conn.execute(
                "SELECT name, project_id, channel FROM features WHERE id = ?", (eid,)
            ).fetchone()
            if r:
                sync.sync_feature_to_cloud(eid, r["name"], r["project_id"], r["channel"])
        elif et == "suite":
            r = conn.execute(
                "SELECT name, project_id, channel FROM suites WHERE id = ?", (eid,)
            ).fetchone()
            if r:
                sync.sync_suite_to_cloud(eid, r["name"], r["project_id"], r["channel"])
        elif et == "script":
            r = conn.execute(
                "SELECT name, feature_id, project_id, file_path, channel, "
                "start_url_key, start_url_value, var_keys, language "
                "FROM scripts WHERE id = ?", (eid,)
            ).fetchone()
            if r:
                import json as _json
                try:
                    var_keys = _json.loads(r["var_keys"] or "[]")
                except (TypeError, ValueError):
                    var_keys = []
                file_content = None
                if r["file_path"]:
                    try:
                        with open(r["file_path"], "r", encoding="utf-8", errors="replace") as f:
                            file_content = f.read()
                    except Exception:
                        pass
                sync.sync_script_to_cloud(
                    eid, r["name"],
                    feature_id=r["feature_id"],
                    project_id=r["project_id"],
                    file_content=file_content,
                    channel=r["channel"],
                    start_url_key=r["start_url_key"],
                    start_url_value=r["start_url_value"],
                    var_keys=var_keys,
                    language=r["language"],
                )
        elif et == "environment":
            r = conn.execute(
                "SELECT name, project_id FROM environments WHERE id = ?", (eid,)
            ).fetchone()
            if r:
                sync.sync_environment_to_cloud(eid, r["name"], r["project_id"])
        elif et == "env_vars":
            sync.sync_env_vars_to_cloud(eid)
        elif et == "suite_items":
            r = conn.execute(
                "SELECT project_id FROM suites WHERE id = ?", (eid,)
            ).fetchone()
            if r:
                sync.sync_suite_items_to_cloud(eid, r["project_id"])
        elif et == "run":
            _dispatch_run(eid, conn, sync)
        else:
            raise ValueError(f"unknown entity_type: {et}")


def _dispatch_run(run_id, conn, sync):
    run = conn.execute(
        "SELECT suite_id, status, started_at, finished_at, browser, resolution, headless, project_id "
        "FROM suite_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if not run:
        return
    script_rows = conn.execute(
        "SELECT scr.script_id, s.name AS script_name, scr.status, scr.duration_ms, "
        "scr.error_message, scr.order_index, scr.console_errors, scr.network_failures, "
        "scr.console_log, scr.network_log, scr.screenshot_path "
        "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
        "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
        (run_id,)
    ).fetchall()
    sync.sync_run_to_cloud(
        run_id=run_id,
        suite_id=run["suite_id"],
        status=run["status"],
        started_at=run["started_at"] or "",
        completed_at=run["finished_at"] or run["started_at"] or "",
        duration_ms=0,
        project_id=run["project_id"],
        browser=run["browser"],
        resolution=run["resolution"],
        headless=bool(run["headless"]) if run["headless"] is not None else None,
        script_results=[
            {
                "script_id": r["script_id"],
                "script_name": r["script_name"],
                "status": r["status"].lower() if r["status"] else "failed",
                "duration_ms": r["duration_ms"] or 0,
                "error_output": r["error_message"],
                "order_index": r["order_index"],
                "console_errors": r["console_errors"] or 0,
                "network_failures": r["network_failures"] or 0,
                "console_log": r["console_log"],
                "network_log": r["network_log"],
                "screenshot_b64": sync._read_screenshot_b64(r["screenshot_path"]),
            }
            for r in script_rows
        ],
    )


def drain_once(max_items=BATCH_SIZE):
    """Drain up to max_items from the queue. Returns (synced, failed, offline)."""
    if not get_auth_key():
        return (0, 0, False)
    if not _is_online():
        return (0, 0, True)

    from cli.db import get_conn
    conn = get_conn()
    rows = _fetch_batch(conn, max_items)
    synced = 0
    failed = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in rows:
        try:
            _dispatch(row)
            conn.execute("DELETE FROM sync_queue WHERE id = ?", (row["id"],))
            conn.commit()
            synced += 1
        except Exception as e:
            failed += 1
            conn.execute(
                "UPDATE sync_queue SET attempts = attempts + 1, "
                "last_error = ?, last_attempt_at = ? WHERE id = ?",
                (str(e)[:500], now_iso, row["id"]),
            )
            conn.commit()
            logger.debug("sync_queue: failed %s %s %s: %s", row["entity_type"], row["entity_id"], row["op"], e)
    return (synced, failed, False)


def _worker_loop():
    backoff_idx = 0
    while True:
        try:
            depth = queue_depth()
            if depth == 0:
                _wake.wait(IDLE_SLEEP)
                _wake.clear()
                continue

            synced, failed, offline = drain_once()

            if offline:
                sleep_for = OFFLINE_BACKOFFS[min(backoff_idx, len(OFFLINE_BACKOFFS) - 1)]
                backoff_idx += 1
                _wake.wait(sleep_for)
                _wake.clear()
                continue

            backoff_idx = 0
            if synced == 0 and failed > 0:
                # Server returned errors (not offline); short pause before retry
                _wake.wait(IDLE_SLEEP)
                _wake.clear()
            # Otherwise loop immediately to drain the rest of the batch
        except Exception as e:
            logger.exception("sync_queue worker error: %s", e)
            _wake.wait(IDLE_SLEEP)
            _wake.clear()


def start_worker():
    """Idempotently start the background drainer daemon thread."""
    global _worker_started
    with _lock:
        if _worker_started:
            _wake.set()
            return
        t = threading.Thread(target=_worker_loop, name="qaclan-sync-queue", daemon=True)
        t.start()
        _worker_started = True
    atexit.register(lambda: flush_sync(2.0))


def trigger_now():
    _wake.set()


def enqueue_all(project_ids=None):
    """Re-enqueue every local entity under the given project_ids (or all if None).
    Returns (enqueued_count, total_queue_depth_after)."""
    from cli.db import get_conn
    conn = get_conn()
    if project_ids is None:
        project_ids = [r["id"] for r in conn.execute("SELECT id FROM projects").fetchall()]
    before = queue_depth()
    for pid in project_ids:
        enqueue("project", pid, "upsert")
        for f in conn.execute("SELECT id FROM features WHERE project_id = ?", (pid,)).fetchall():
            enqueue("feature", f["id"], "upsert")
        for s in conn.execute("SELECT id FROM suites WHERE project_id = ?", (pid,)).fetchall():
            enqueue("suite", s["id"], "upsert")
            enqueue("suite_items", s["id"], "upsert")
        for sc in conn.execute("SELECT id FROM scripts WHERE project_id = ?", (pid,)).fetchall():
            enqueue("script", sc["id"], "upsert")
        for env in conn.execute("SELECT id FROM environments WHERE project_id = ?", (pid,)).fetchall():
            enqueue("environment", env["id"], "upsert")
            enqueue("env_vars", env["id"], "upsert")
        for run in conn.execute("SELECT id FROM suite_runs WHERE project_id = ?", (pid,)).fetchall():
            enqueue("run", run["id"], "upsert")
    after = queue_depth()
    return (after - before, after)


def flush_sync(deadline=5.0):
    """Blocking best-effort drain with wall-clock cap. Used by short-lived CLI commands."""
    if not get_auth_key():
        return
    end = time.monotonic() + max(0.0, deadline)
    while time.monotonic() < end:
        if queue_depth() == 0:
            return
        synced, failed, offline = drain_once()
        if offline:
            return
        if synced == 0:
            return
