import click
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table

from cli.config import get_active_project
from cli.db import get_conn, generate_id

console = Console()


@click.group()
def feature():
    """Manage web features."""
    pass


@feature.command("create")
@click.argument("name")
def feature_create(name):
    """Create a new web feature."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    fid = generate_id("feat")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO features (id, project_id, channel, name, created_at) VALUES (?, ?, 'web', ?, ?)",
        (fid, proj["id"], name, now),
    )
    conn.commit()
    console.print(f"[green]✓[/green] Feature created: {name} [{fid}]  [bold cyan]\\[WEB][/bold cyan]")
    from cli.sync import sync_feature_to_cloud
    sync_feature_to_cloud(fid, name, proj["id"])


@feature.command("list")
def feature_list():
    """List all web features."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    rows = conn.execute(
        "SELECT f.id, f.name, COUNT(s.id) as script_count "
        "FROM features f LEFT JOIN scripts s ON s.feature_id = f.id "
        "WHERE f.project_id = ? AND f.channel = 'web' "
        "GROUP BY f.id ORDER BY f.name",
        (proj["id"],),
    ).fetchall()
    if not rows:
        console.print("No web features. Run: [bold]qaclan web feature create \"name\"[/bold]")
        return
    table = Table()
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Scripts")
    for r in rows:
        count_str = str(r["script_count"])
        if r["script_count"] == 0:
            count_str += "  [yellow]⚠[/yellow]"
        table.add_row(r["id"], r["name"], count_str)
    console.print(table)


@feature.command("delete")
@click.argument("feature_id")
def feature_delete(feature_id):
    """Delete a web feature."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM features WHERE id = ? AND project_id = ?",
        (feature_id, proj["id"]),
    ).fetchone()
    if not row:
        console.print(f"[red]Feature {feature_id} not found. Run: qaclan web feature list[/red]")
        return
    scripts = conn.execute("SELECT COUNT(*) as cnt FROM scripts WHERE feature_id = ?", (feature_id,)).fetchone()
    msg = f"Delete feature '{row['name']}'?"
    if scripts["cnt"] > 0:
        console.print(f"[yellow]⚠[/yellow] This feature has {scripts['cnt']} script(s) that will also be deleted.")
        msg = f"Delete feature '{row['name']}' and its {scripts['cnt']} script(s)?"
    if not click.confirm(msg):
        return
    conn.execute("DELETE FROM scripts WHERE feature_id = ?", (feature_id,))
    conn.execute("DELETE FROM features WHERE id = ?", (feature_id,))
    conn.commit()
    console.print(f"[green]✓[/green] Feature deleted: {row['name']}")
