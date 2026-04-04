import os
import click
from datetime import datetime, timezone
from rich.console import Console

from cli.config import get_auth_key, set_active_project_id, get_active_project_id, SCRIPTS_DIR
from cli.db import get_conn, generate_id
from cli import api

console = Console()


@click.command()
def pull():
    """Download team workspace from cloud."""
    key = get_auth_key()
    if not key:
        console.print("[red]Not logged in. Run: qaclan login[/red]")
        return

    console.print("[dim]Pulling workspace from cloud...[/dim]")
    try:
        data = api.pull_workspace(key)
    except Exception as e:
        console.print(f"[red]Pull failed: {e}[/red]")
        return

    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()

    # Track cloud_id -> local_id mappings for resolving foreign keys
    project_map = {}   # cloud project id -> local project id
    feature_map = {}   # cloud feature id -> local feature id
    suite_map = {}     # cloud suite id -> local suite id
    script_map = {}    # cloud script cli_script_id -> local script id
    env_map = {}       # cloud environment id -> local environment id

    counts = {"projects": 0, "features": 0, "scripts": 0, "suites": 0, "environments": 0, "env_vars": 0}

    # 1. Projects
    for p in data.get("projects", []):
        cloud_id = p["id"]
        existing = conn.execute("SELECT id FROM projects WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE projects SET name = ? WHERE id = ?", (p["name"], existing["id"]))
            project_map[cloud_id] = existing["id"]
        else:
            local_id = generate_id("proj")
            conn.execute(
                "INSERT INTO projects (id, name, created_at, cloud_id) VALUES (?, ?, ?, ?)",
                (local_id, p["name"], now, cloud_id),
            )
            project_map[cloud_id] = local_id
            counts["projects"] += 1
            console.print(f"  [green]✓[/green] Project: {p['name']}")

    # 2. Features
    for f in data.get("features", []):
        cloud_id = f["id"]
        existing = conn.execute("SELECT id FROM features WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE features SET name = ? WHERE id = ?", (f["name"], existing["id"]))
            feature_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(f["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("feat")
            conn.execute(
                "INSERT INTO features (id, project_id, channel, name, created_at, cloud_id) VALUES (?, ?, 'web', ?, ?, ?)",
                (local_id, local_project_id, f["name"], now, cloud_id),
            )
            feature_map[cloud_id] = local_id
            counts["features"] += 1
            console.print(f"  [green]✓[/green] Feature: {f['name']}")

    # 3. Scripts (need feature_id and project_id resolved)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    for s in data.get("scripts", []):
        cloud_id = s["id"]
        existing = conn.execute("SELECT id, file_path FROM scripts WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            # Update name and file content
            conn.execute("UPDATE scripts SET name = ? WHERE id = ?", (s["name"], existing["id"]))
            file_content = s.get("file_content")
            if file_content and existing["file_path"]:
                with open(existing["file_path"], "w") as fp:
                    fp.write(file_content)
            script_map[s.get("cli_script_id", cloud_id)] = existing["id"]
        else:
            local_feature_id = feature_map.get(s.get("feature_id"))
            local_project_id = project_map.get(s.get("project_id"))
            if not local_feature_id or not local_project_id:
                console.print(f"  [yellow]⚠[/yellow] Script skipped (missing parent): {s['name']}")
                continue
            file_content = s.get("file_content")
            if not file_content:
                console.print(f"  [yellow]⚠[/yellow] Script skipped (no content): {s['name']}")
                continue
            local_id = generate_id("script")
            file_path = os.path.join(SCRIPTS_DIR, f"{local_id}.py")
            with open(file_path, "w") as fp:
                fp.write(file_content)
            created_by = s.get("created_by")
            conn.execute(
                "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, created_at, cloud_id, created_by) "
                "VALUES (?, ?, ?, 'web', ?, ?, 'PULLED', ?, ?, ?)",
                (local_id, local_feature_id, local_project_id, s["name"], file_path, now, cloud_id, created_by),
            )
            script_map[s.get("cli_script_id", cloud_id)] = local_id
            counts["scripts"] += 1
            console.print(f"  [green]✓[/green] Script: {s['name']}")

    # 4. Environments
    for e in data.get("environments", []):
        cloud_id = e["id"]
        existing = conn.execute("SELECT id FROM environments WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE environments SET name = ? WHERE id = ?", (e["name"], existing["id"]))
            env_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(e["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("env")
            conn.execute(
                "INSERT INTO environments (id, project_id, name, created_at, cloud_id) VALUES (?, ?, ?, ?, ?)",
                (local_id, local_project_id, e["name"], now, cloud_id),
            )
            env_map[cloud_id] = local_id
            counts["environments"] += 1
            console.print(f"  [green]✓[/green] Environment: {e['name']}")

    # 5. Environment variables
    for v in data.get("env_vars", []):
        local_env_id = env_map.get(v["environment_id"])
        if not local_env_id:
            continue
        existing = conn.execute(
            "SELECT id FROM env_vars WHERE environment_id = ? AND key = ?",
            (local_env_id, v["key"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE env_vars SET value = ?, is_secret = ? WHERE id = ?",
                (v["value"], 1 if v.get("is_secret") else 0, existing["id"]),
            )
        else:
            local_id = generate_id("evar")
            conn.execute(
                "INSERT INTO env_vars (id, environment_id, key, value, is_secret) VALUES (?, ?, ?, ?, ?)",
                (local_id, local_env_id, v["key"], v["value"], 1 if v.get("is_secret") else 0),
            )
            counts["env_vars"] += 1

    # 6. Suites
    for s in data.get("suites", []):
        cloud_id = s["id"]
        existing = conn.execute("SELECT id FROM suites WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE suites SET name = ? WHERE id = ?", (s["name"], existing["id"]))
            suite_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(s["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("suite")
            conn.execute(
                "INSERT INTO suites (id, project_id, channel, name, created_at, cloud_id) VALUES (?, ?, 'web', ?, ?, ?)",
                (local_id, local_project_id, s["name"], now, cloud_id),
            )
            suite_map[cloud_id] = local_id
            counts["suites"] += 1
            console.print(f"  [green]✓[/green] Suite: {s['name']}")

    # 7. Suite items
    for si in data.get("suite_items", []):
        local_suite_id = suite_map.get(si["suite_id"])
        local_script_id = script_map.get(si["cli_script_id"])
        if not local_suite_id or not local_script_id:
            continue
        existing = conn.execute(
            "SELECT id FROM suite_items WHERE suite_id = ? AND script_id = ?",
            (local_suite_id, local_script_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE suite_items SET order_index = ? WHERE id = ?",
                (si["order_index"], existing["id"]),
            )
        else:
            local_id = generate_id("si")
            conn.execute(
                "INSERT INTO suite_items (id, suite_id, script_id, order_index, created_at) VALUES (?, ?, ?, ?, ?)",
                (local_id, local_suite_id, local_script_id, si["order_index"], now),
            )

    conn.commit()

    # Set first pulled project as active if no active project
    if not get_active_project_id() and project_map:
        first_local_id = next(iter(project_map.values()))
        set_active_project_id(first_local_id)
        proj_name = conn.execute("SELECT name FROM projects WHERE id = ?", (first_local_id,)).fetchone()
        if proj_name:
            console.print(f"\n[bold]Active project set to: {proj_name['name']}[/bold]")

    # Summary
    total = sum(counts.values())
    if total == 0:
        console.print("\n[dim]Everything up to date — nothing new to pull.[/dim]")
    else:
        console.print(
            f"\n[bold]Pulled:[/bold] {counts['projects']} projects, {counts['features']} features, "
            f"{counts['scripts']} scripts, {counts['suites']} suites, "
            f"{counts['environments']} environments, {counts['env_vars']} env vars"
        )
