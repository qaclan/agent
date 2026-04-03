"""Cloud sync helper. Wraps cli/api.py calls with error handling.
Sync is best-effort — failures print a warning but never block the CLI."""

import base64
import os

from rich.console import Console
from cli.config import get_auth_key
from cli import api

console = Console()


def _read_screenshot_b64(path):
    """Read a screenshot file and return base64-encoded content, or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def _try_sync(label, fn):
    """Run a sync function, catch and warn on failure."""
    try:
        return fn()
    except Exception as e:
        console.print(f"[yellow]⚠ Cloud sync failed ({label}): {e}[/yellow]")
        return None


def _save_cloud_id(table, local_id, cloud_id):
    """Store the cloud UUID for a local entity."""
    from cli.db import get_conn
    get_conn().execute(f"UPDATE {table} SET cloud_id = ? WHERE id = ?", (cloud_id, local_id))
    get_conn().commit()


def _get_cloud_id(table, local_id):
    """Get the cloud UUID for a local entity, or None."""
    from cli.db import get_conn
    row = get_conn().execute(f"SELECT cloud_id FROM {table} WHERE id = ?", (local_id,)).fetchone()
    return row["cloud_id"] if row and row["cloud_id"] else None


def sync_project_to_cloud(project_id, name):
    """Sync a project. Returns cloud project ID or None."""
    key = get_auth_key()
    if not key:
        return None
    result = _try_sync("project", lambda: api.sync_project(key, {
        "cli_project_id": project_id,
        "name": name,
    }))
    if result:
        _save_cloud_id("projects", project_id, result["id"])
        return result["id"]
    return None


def _ensure_project_synced(project_id):
    """Ensure the project has a cloud_id. If not, sync it now."""
    cloud_project_id = _get_cloud_id("projects", project_id)
    if cloud_project_id:
        return cloud_project_id
    # Project was created before sync was added — sync it now
    from cli.db import get_conn
    row = get_conn().execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        return None
    return sync_project_to_cloud(project_id, row["name"])


def _ensure_suite_synced(suite_id, project_id):
    """Ensure the suite has a cloud_id. If not, sync it now (which also ensures the project)."""
    cloud_suite_id = _get_cloud_id("suites", suite_id)
    if cloud_suite_id:
        return cloud_suite_id
    from cli.db import get_conn
    row = get_conn().execute("SELECT name FROM suites WHERE id = ?", (suite_id,)).fetchone()
    if not row:
        return None
    result = sync_suite_to_cloud(suite_id, row["name"], project_id)
    if result:
        return result.get("id") or _get_cloud_id("suites", suite_id)
    return None


def sync_feature_to_cloud(feature_id, name, project_id, channel=None):
    """Sync a feature. Requires cloud_project_id."""
    key = get_auth_key()
    if not key:
        return None
    cloud_project_id = _ensure_project_synced(project_id)
    if not cloud_project_id:
        return None
    if not channel:
        from cli.db import get_conn
        row = get_conn().execute("SELECT channel FROM features WHERE id = ?", (feature_id,)).fetchone()
        channel = row["channel"] if row else "web"
    result = _try_sync("feature", lambda: api.sync_feature(key, {
        "cli_feature_id": feature_id,
        "name": name,
        "project_id": cloud_project_id,
        "channel": channel,
    }))
    if result:
        _save_cloud_id("features", feature_id, result["id"])
    return result


def sync_suite_to_cloud(suite_id, name, project_id, channel=None):
    """Sync a suite. Requires cloud_project_id."""
    key = get_auth_key()
    if not key:
        return None
    cloud_project_id = _ensure_project_synced(project_id)
    if not cloud_project_id:
        return None
    if not channel:
        from cli.db import get_conn
        row = get_conn().execute("SELECT channel FROM suites WHERE id = ?", (suite_id,)).fetchone()
        channel = row["channel"] if row else "web"
    result = _try_sync("suite", lambda: api.sync_suite(key, {
        "cli_suite_id": suite_id,
        "name": name,
        "project_id": cloud_project_id,
        "channel": channel,
    }))
    if result:
        _save_cloud_id("suites", suite_id, result["id"])
    return result


def sync_script_to_cloud(script_id, name, suite_id=None, feature_id=None, project_id=None, file_content=None, channel=None):
    """Sync a script. IDs are LOCAL IDs (optional)."""
    key = get_auth_key()
    if not key:
        return None
    if not channel:
        from cli.db import get_conn
        row = get_conn().execute("SELECT channel FROM scripts WHERE id = ?", (script_id,)).fetchone()
        channel = row["channel"] if row else "web"
    payload = {"cli_script_id": script_id, "name": name, "channel": channel}
    if suite_id:
        cloud_suite_id = _get_cloud_id("suites", suite_id)
        if cloud_suite_id:
            payload["suite_id"] = cloud_suite_id
    if feature_id:
        cloud_feature_id = _get_cloud_id("features", feature_id)
        if cloud_feature_id:
            payload["feature_id"] = cloud_feature_id
    if project_id:
        cloud_project_id = _get_cloud_id("projects", project_id)
        if cloud_project_id:
            payload["project_id"] = cloud_project_id
    if file_content is not None:
        payload["file_content"] = file_content
    return _try_sync("script", lambda: api.sync_script(key, payload))


# --- Delete operations ---

def delete_project_from_cloud(project_id):
    """Delete a project from cloud by CLI project ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete project", lambda: api.delete_project(key, project_id))


def delete_feature_from_cloud(feature_id):
    """Delete a feature from cloud by CLI feature ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete feature", lambda: api.delete_feature(key, feature_id))


def delete_suite_from_cloud(suite_id):
    """Delete a suite from cloud by CLI suite ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete suite", lambda: api.delete_suite(key, suite_id))


def delete_script_from_cloud(script_id):
    """Delete a script from cloud by CLI script ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete script", lambda: api.delete_script(key, script_id))


def delete_environment_from_cloud(env_id):
    """Delete an environment from cloud by CLI environment ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete environment", lambda: api.delete_environment(key, env_id))


# --- Suite items sync ---

def sync_suite_items_to_cloud(suite_id, project_id):
    """Read suite items from local DB and push full list to cloud."""
    key = get_auth_key()
    if not key:
        return None
    _ensure_suite_synced(suite_id, project_id)
    from cli.db import get_conn
    items = get_conn().execute(
        "SELECT script_id, order_index FROM suite_items WHERE suite_id = ? ORDER BY order_index",
        (suite_id,)
    ).fetchall()
    return _try_sync("suite items", lambda: api.sync_suite_items(key, {
        "cli_suite_id": str(suite_id),
        "items": [{"cli_script_id": str(r["script_id"]), "order_index": r["order_index"]} for r in items],
    }))


# --- Environment sync ---

def sync_environment_to_cloud(env_id, name, project_id):
    """Sync an environment to cloud."""
    key = get_auth_key()
    if not key:
        return None
    cloud_project_id = _ensure_project_synced(project_id)
    if not cloud_project_id:
        return None
    return _try_sync("environment", lambda: api.sync_environment(key, {
        "cli_environment_id": str(env_id),
        "name": name,
        "project_id": cloud_project_id,
    }))


def sync_env_vars_to_cloud(env_id):
    """Read env vars from local DB and push full list to cloud."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    rows = get_conn().execute(
        "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?", (env_id,)
    ).fetchall()
    return _try_sync("env vars", lambda: api.sync_env_vars(key, {
        "cli_environment_id": str(env_id),
        "vars": [{"key": r["key"], "value": r["value"], "is_secret": bool(r["is_secret"])} for r in rows],
    }))


def sync_all(project_id=None):
    """Push all local data to cloud. Syncs projects, features, suites, scripts, and past runs."""
    from cli.db import get_conn
    key = get_auth_key()
    if not key:
        console.print("[red]✗ Not logged in. Run 'qaclan login' first.[/red]")
        return

    conn = get_conn()

    # Determine which projects to sync
    if project_id:
        projects = conn.execute("SELECT id, name FROM projects WHERE id = ?", (project_id,)).fetchall()
    else:
        projects = conn.execute("SELECT id, name FROM projects").fetchall()

    if not projects:
        console.print("[yellow]No projects to sync.[/yellow]")
        return

    total_synced = {"projects": 0, "features": 0, "suites": 0, "scripts": 0, "environments": 0, "runs": 0}

    for proj in projects:
        pid = proj["id"]
        console.print(f"\n[bold]Syncing project: {proj['name']}[/bold]")

        # Project
        cloud_pid = sync_project_to_cloud(pid, proj["name"])
        if not cloud_pid:
            console.print(f"  [yellow]⚠ Could not sync project, skipping children[/yellow]")
            continue
        total_synced["projects"] += 1

        # Features
        features = conn.execute(
            "SELECT id, name FROM features WHERE project_id = ?", (pid,)
        ).fetchall()
        for f in features:
            result = sync_feature_to_cloud(f["id"], f["name"], pid)
            if result:
                total_synced["features"] += 1
                console.print(f"  [green]✓[/green] Feature: {f['name']}")
            else:
                console.print(f"  [yellow]⚠[/yellow] Feature: {f['name']}")

        # Suites
        suites = conn.execute(
            "SELECT id, name FROM suites WHERE project_id = ?", (pid,)
        ).fetchall()
        for s in suites:
            result = sync_suite_to_cloud(s["id"], s["name"], pid)
            if result:
                total_synced["suites"] += 1
                console.print(f"  [green]✓[/green] Suite: {s['name']}")
            else:
                console.print(f"  [yellow]⚠[/yellow] Suite: {s['name']}")

        # Scripts (with feature_id, project_id, and file content)
        scripts = conn.execute(
            "SELECT id, name, feature_id, project_id, file_path FROM scripts WHERE project_id = ?", (pid,)
        ).fetchall()
        for sc in scripts:
            file_content = None
            if sc["file_path"]:
                try:
                    with open(sc["file_path"], "r") as f:
                        file_content = f.read()
                except Exception:
                    pass
            result = sync_script_to_cloud(
                sc["id"], sc["name"],
                feature_id=sc["feature_id"],
                project_id=sc["project_id"],
                file_content=file_content,
            )
            if result:
                total_synced["scripts"] += 1
                console.print(f"  [green]✓[/green] Script: {sc['name']}")
            else:
                console.print(f"  [yellow]⚠[/yellow] Script: {sc['name']}")

        # Suite items
        for s in suites:
            result = sync_suite_items_to_cloud(s["id"], pid)
            if result:
                console.print(f"  [green]✓[/green] Suite items: {s['name']}")

        # Environments
        envs = conn.execute(
            "SELECT id, name FROM environments WHERE project_id = ?", (pid,)
        ).fetchall()
        for env in envs:
            result = sync_environment_to_cloud(env["id"], env["name"], pid)
            if result:
                total_synced["environments"] += 1
                console.print(f"  [green]✓[/green] Environment: {env['name']}")
                # Sync env vars
                sync_env_vars_to_cloud(env["id"])
            else:
                console.print(f"  [yellow]⚠[/yellow] Environment: {env['name']}")

        # Past runs
        runs = conn.execute(
            "SELECT sr.id, sr.suite_id, sr.status, sr.started_at, sr.finished_at "
            "FROM suite_runs sr WHERE sr.project_id = ? ORDER BY sr.started_at",
            (pid,)
        ).fetchall()
        for run in runs:
            script_run_rows = conn.execute(
                "SELECT scr.script_id, s.name as script_name, scr.status, scr.duration_ms, "
                "scr.error_message, scr.order_index, scr.console_errors, scr.network_failures, "
                "scr.console_log, scr.network_log, scr.screenshot_path "
                "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
                "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
                (run["id"],)
            ).fetchall()
            started = run["started_at"] or ""
            finished = run["finished_at"] or started
            result = sync_run_to_cloud(
                run_id=run["id"],
                suite_id=run["suite_id"],
                status=run["status"],
                started_at=started,
                completed_at=finished,
                duration_ms=0,
                project_id=pid,
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
                        "screenshot_b64": _read_screenshot_b64(r["screenshot_path"]),
                    }
                    for r in script_run_rows
                ],
            )
            if result:
                total_synced["runs"] += 1
                console.print(f"  [green]✓[/green] Run: {run['id']} [{run['status']}]")
            else:
                console.print(f"  [yellow]⚠[/yellow] Run: {run['id']}")

    console.print(f"\n[bold]Sync complete:[/bold] "
                  f"{total_synced['projects']} projects, "
                  f"{total_synced['features']} features, "
                  f"{total_synced['suites']} suites, "
                  f"{total_synced['scripts']} scripts, "
                  f"{total_synced['environments']} environments, "
                  f"{total_synced['runs']} runs")


def sync_run_to_cloud(run_id, suite_id, status, started_at, completed_at, duration_ms, script_results, project_id=None):
    """Sync a completed test run with all script results.
    Ensures the parent suite (and its project) are synced first."""
    key = get_auth_key()
    if not key:
        return None
    if project_id and suite_id:
        _ensure_suite_synced(suite_id, project_id)
    return _try_sync("run", lambda: api.sync_run(key, {
        "run_id": run_id,
        "suite_id": suite_id,
        "status": status.lower(),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "script_results": script_results,
    }))
