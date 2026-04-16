import json
import os

import click
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table

from cli.config import get_active_project, SCRIPTS_DIR
from cli.db import get_conn, generate_id
from cli.script_strategies import get_strategy, SUPPORTED_LANGUAGES
from cli.script_strategies._shared import scan_var_keys as _scan_var_keys

console = Console()


@click.group()
def script():
    """Manage web scripts."""
    pass


@script.command("list")
@click.option("--feature", "feature_id", default=None, help="Filter by feature ID")
def script_list(feature_id):
    """List web scripts."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    if feature_id:
        rows = conn.execute(
            "SELECT s.id, s.name, f.name as feature_name, s.source, s.created_by "
            "FROM scripts s JOIN features f ON s.feature_id = f.id "
            "WHERE s.project_id = ? AND s.channel = 'web' AND s.feature_id = ? "
            "ORDER BY f.name, s.name",
            (proj["id"], feature_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT s.id, s.name, f.name as feature_name, s.source, s.created_by "
            "FROM scripts s JOIN features f ON s.feature_id = f.id "
            "WHERE s.project_id = ? AND s.channel = 'web' "
            "ORDER BY f.name, s.name",
            (proj["id"],),
        ).fetchall()
    if not rows:
        console.print("No web scripts. Record one: [bold]qaclan web record --feature <id> --name \"name\"[/bold]")
        return
    table = Table()
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Feature")
    table.add_column("Source")
    table.add_column("Created By")
    for r in rows:
        table.add_row(r["id"], r["name"], r["feature_name"], r["source"], r["created_by"] or "")
    console.print(table)


@script.command("show")
@click.argument("script_id")
def script_show(script_id):
    """Show script content."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scripts WHERE id = ? AND project_id = ?",
        (script_id, proj["id"]),
    ).fetchone()
    if not row:
        console.print(f"[red]Script {script_id} not found. Run: qaclan web script list[/red]")
        return
    if not os.path.exists(row["file_path"]):
        console.print(f"[red]Script file not found at {row['file_path']}[/red]")
        return
    with open(row["file_path"], "r") as f:
        console.print(f.read())


@script.command("import")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--name", required=True, help="Name for the script")
@click.option("--feature", "feature_id", required=True, help="Feature ID")
@click.option("--language", type=click.Choice(list(SUPPORTED_LANGUAGES)), default="python",
              help="Playwright binding the script was written against")
def script_import(file_path, name, feature_id, language):
    """Import an external Playwright codegen script."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    feat = conn.execute(
        "SELECT * FROM features WHERE id = ? AND project_id = ?",
        (feature_id, proj["id"]),
    ).fetchone()
    if not feat:
        console.print(f"[red]Feature {feature_id} not found. Run: qaclan web feature list[/red]")
        return

    strategy = get_strategy(language)
    script_id = generate_id("script")
    dest = os.path.join(SCRIPTS_DIR, f"{script_id}{strategy.file_extension}")
    os.makedirs(SCRIPTS_DIR, exist_ok=True)

    with open(file_path, "r") as f:
        raw_script = f.read()
    processed = strategy.post_process_recording(raw_script)
    with open(dest, "w") as f:
        f.write(processed)

    var_keys_list = _scan_var_keys(processed)

    now = datetime.now(timezone.utc).isoformat()
    from cli.config import get_user_name
    created_by = get_user_name()
    conn.execute(
        "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, language, "
        "created_at, created_by, var_keys) "
        "VALUES (?, ?, ?, 'web', ?, ?, 'UPLOADED', ?, ?, ?, ?)",
        (script_id, feature_id, proj["id"], name, dest, language, now, created_by, json.dumps(var_keys_list)),
    )
    conn.commit()
    console.print(f"[green]✓[/green] Script imported: {name} [{script_id}]")
    from cli.sync_queue import enqueue
    enqueue("script", script_id, "upsert")
    console.print(f"  Feature: {feat['name']}")
    console.print(f"  File: {dest}")


@script.command("delete")
@click.argument("script_id")
def script_delete(script_id):
    """Delete a script."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scripts WHERE id = ? AND project_id = ?",
        (script_id, proj["id"]),
    ).fetchone()
    if not row:
        console.print(f"[red]Script {script_id} not found. Run: qaclan web script list[/red]")
        return
    suites = conn.execute(
        "SELECT s.name FROM suite_items si JOIN suites s ON si.suite_id = s.id WHERE si.script_id = ?",
        (script_id,),
    ).fetchall()
    msg = f"Delete script '{row['name']}'?"
    if suites:
        suite_names = ", ".join(s["name"] for s in suites)
        console.print(f"[yellow]⚠[/yellow] This script is in suite(s): {suite_names}")
        msg = f"Delete script '{row['name']}' and remove it from {len(suites)} suite(s)?"
    if not click.confirm(msg):
        return
    conn.execute("DELETE FROM suite_items WHERE script_id = ?", (script_id,))
    conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
    conn.commit()
    if os.path.exists(row["file_path"]):
        os.unlink(row["file_path"])
    console.print(f"[green]✓[/green] Script deleted: {row['name']}")
    from cli.sync_queue import enqueue
    enqueue("script", script_id, "delete")
