import click
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table

from cli.config import get_active_project, set_active_project_id
from cli.db import get_conn, generate_id

console = Console()


@click.group()
def project():
    """Manage projects."""
    pass


@project.command("create")
@click.argument("name")
def project_create(name):
    """Create a new project and set it as active."""
    conn = get_conn()
    pid = generate_id("proj")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)", (pid, name, now))
    conn.commit()
    set_active_project_id(pid)
    console.print(f"[green]✓[/green] Project created: {name} [{pid}]")
    console.print(f"Active project set to: {name}")


@project.command("list")
def project_list():
    """List all projects."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
    if not rows:
        console.print("No projects found. Run: [bold]qaclan project create \"name\"[/bold]")
        return
    table = Table()
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Created")
    for r in rows:
        created = r["created_at"][:10]
        table.add_row(r["id"], r["name"], created)
    console.print(table)


@project.command("use")
@click.argument("project_id")
def project_use(project_id):
    """Switch the active project."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        console.print(f"[red]Project {project_id} not found. Run: qaclan project list[/red]")
        return
    set_active_project_id(project_id)
    console.print(f"[green]✓[/green] Active project: {row['name']}")


@project.command("show")
def project_show():
    """Show the active project."""
    proj = get_active_project(console)
    if not proj:
        return
    console.print(f"Active project: {proj['name']} [{proj['id']}]")
