import click
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table

from cli.config import get_active_project
from cli.db import get_conn, generate_id

console = Console()


@click.group()
def suite():
    """Manage web test suites."""
    pass


@suite.command("create")
@click.argument("name")
def suite_create(name):
    """Create a new web suite."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    sid = generate_id("suite")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO suites (id, project_id, channel, name, created_at) VALUES (?, ?, 'web', ?, ?)",
        (sid, proj["id"], name, now),
    )
    conn.commit()
    console.print(f"[green]✓[/green] Suite created: {name} [{sid}]  [bold cyan]\\[WEB][/bold cyan]")
    from cli.sync import sync_suite_to_cloud
    sync_suite_to_cloud(sid, name, proj["id"])


@suite.command("add")
@click.option("--suite", "suite_id", required=True, help="Suite ID")
@click.option("--script", "script_id", required=True, help="Script ID to add")
def suite_add(suite_id, script_id):
    """Add a script to a suite."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    s = conn.execute(
        "SELECT * FROM suites WHERE id = ? AND project_id = ?", (suite_id, proj["id"])
    ).fetchone()
    if not s:
        console.print(f"[red]Suite {suite_id} not found. Run: qaclan web suite list[/red]")
        return
    sc = conn.execute(
        "SELECT * FROM scripts WHERE id = ? AND project_id = ?", (script_id, proj["id"])
    ).fetchone()
    if not sc:
        console.print(f"[red]Script {script_id} not found. Run: qaclan web script list[/red]")
        return
    if sc["channel"] != s["channel"]:
        console.print(
            f"[red]Script {script_id} is a {sc['channel'].upper()} script. "
            f"Suite {suite_id} is a {s['channel'].upper()} suite.[/red]"
        )
        return
    max_order = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) as m FROM suite_items WHERE suite_id = ?", (suite_id,)
    ).fetchone()["m"]
    item_id = generate_id("si")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO suite_items (id, suite_id, script_id, order_index, created_at) VALUES (?, ?, ?, ?, ?)",
        (item_id, suite_id, script_id, max_order + 1, now),
    )
    conn.commit()
    console.print(f"[green]✓[/green] Added {sc['name']} to {s['name']} [order: {max_order + 1}]")


@suite.command("reorder")
@click.option("--suite", "suite_id", required=True, help="Suite ID")
@click.option("--scripts", required=True, help="Comma-separated script IDs in desired order")
def suite_reorder(suite_id, scripts):
    """Reorder scripts in a suite."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    s = conn.execute(
        "SELECT * FROM suites WHERE id = ? AND project_id = ?", (suite_id, proj["id"])
    ).fetchone()
    if not s:
        console.print(f"[red]Suite {suite_id} not found. Run: qaclan web suite list[/red]")
        return
    script_ids = [sid.strip() for sid in scripts.split(",")]
    for idx, sid in enumerate(script_ids):
        conn.execute(
            "UPDATE suite_items SET order_index = ? WHERE suite_id = ? AND script_id = ?",
            (idx, suite_id, sid),
        )
    conn.commit()
    console.print(f"[green]✓[/green] Reordered {len(script_ids)} scripts in {s['name']}")


@suite.command("remove")
@click.option("--suite", "suite_id", required=True, help="Suite ID")
@click.option("--script", "script_id", required=True, help="Script ID to remove")
def suite_remove(suite_id, script_id):
    """Remove a script from a suite."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    s = conn.execute(
        "SELECT * FROM suites WHERE id = ? AND project_id = ?", (suite_id, proj["id"])
    ).fetchone()
    if not s:
        console.print(f"[red]Suite {suite_id} not found. Run: qaclan web suite list[/red]")
        return
    conn.execute(
        "DELETE FROM suite_items WHERE suite_id = ? AND script_id = ?", (suite_id, script_id)
    )
    conn.commit()
    console.print(f"[green]✓[/green] Removed script from {s['name']}")


@suite.command("show")
@click.option("--suite", "suite_id", required=True, help="Suite ID")
def suite_show(suite_id):
    """Show suite details."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    s = conn.execute(
        "SELECT * FROM suites WHERE id = ? AND project_id = ?", (suite_id, proj["id"])
    ).fetchone()
    if not s:
        console.print(f"[red]Suite {suite_id} not found. Run: qaclan web suite list[/red]")
        return
    console.print(f"[bold]{s['name']}[/bold] [{s['id']}]  {s['channel'].upper()}")
    items = conn.execute(
        "SELECT si.order_index, sc.id as script_id, sc.name as script_name, f.name as feature_name "
        "FROM suite_items si "
        "JOIN scripts sc ON si.script_id = sc.id "
        "JOIN features f ON sc.feature_id = f.id "
        "WHERE si.suite_id = ? ORDER BY si.order_index",
        (suite_id,),
    ).fetchall()
    if not items:
        console.print("  (no scripts)")
    else:
        for i, item in enumerate(items):
            prefix = "└──" if i == len(items) - 1 else "├──"
            console.print(
                f"{prefix} [{item['order_index'] + 1}] {item['script_name']}       "
                f"{item['script_id']}   {item['feature_name']}"
            )
    if s["first_run_at"]:
        console.print(f"\nFirst run: {s['first_run_at'][:10]}")
    if s["last_run_at"]:
        status_color = "green" if s["last_run_status"] == "PASSED" else "red"
        console.print(
            f"Last run:  {s['last_run_at'][:10]} — [{status_color}]{s['last_run_status']}[/{status_color}]"
        )


@suite.command("list")
def suite_list():
    """List all web suites."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    rows = conn.execute(
        "SELECT s.id, s.name, s.last_run_at, s.last_run_status, "
        "COUNT(si.id) as script_count "
        "FROM suites s LEFT JOIN suite_items si ON si.suite_id = s.id "
        "WHERE s.project_id = ? AND s.channel = 'web' "
        "GROUP BY s.id ORDER BY s.name",
        (proj["id"],),
    ).fetchall()
    if not rows:
        console.print("No web suites. Run: [bold]qaclan web suite create \"name\"[/bold]")
        return
    table = Table()
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Scripts")
    table.add_column("Last Run")
    table.add_column("Status")
    for r in rows:
        last_run = r["last_run_at"][:16] if r["last_run_at"] else "—"
        status = r["last_run_status"] or "—"
        table.add_row(r["id"], r["name"], str(r["script_count"]), last_run, status)
    console.print(table)


@suite.command("delete")
@click.argument("suite_id")
def suite_delete(suite_id):
    """Delete a suite."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    s = conn.execute(
        "SELECT * FROM suites WHERE id = ? AND project_id = ?", (suite_id, proj["id"])
    ).fetchone()
    if not s:
        console.print(f"[red]Suite {suite_id} not found. Run: qaclan web suite list[/red]")
        return
    if not click.confirm(f"Delete suite '{s['name']}'?"):
        return
    conn.execute("DELETE FROM suite_items WHERE suite_id = ?", (suite_id,))
    conn.execute("DELETE FROM suites WHERE id = ?", (suite_id,))
    conn.commit()
    console.print(f"[green]✓[/green] Suite deleted: {s['name']}")
