import click
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table

from cli.config import get_active_project
from cli.db import get_conn, generate_id

console = Console()


@click.group("env")
def env_group():
    """Manage environments and variables."""
    pass


@env_group.command("create")
@click.argument("name")
def env_create(name):
    """Create a new environment."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    eid = generate_id("env")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO environments (id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (eid, proj["id"], name, now),
    )
    conn.commit()
    console.print(f"[green]✓[/green] Environment created: {name} [{eid}]")


@env_group.command("set")
@click.argument("env_name")
@click.argument("key")
@click.argument("value")
@click.option("--secret", is_flag=True, help="Mask value in list output")
def env_set(env_name, key, value, secret):
    """Set an environment variable."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    env_row = conn.execute(
        "SELECT * FROM environments WHERE project_id = ? AND name = ?",
        (proj["id"], env_name),
    ).fetchone()
    if not env_row:
        console.print(f'[red]Environment "{env_name}" not found. Run: qaclan env create {env_name}[/red]')
        return
    existing = conn.execute(
        "SELECT * FROM env_vars WHERE environment_id = ? AND key = ?",
        (env_row["id"], key),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE env_vars SET value = ?, is_secret = ? WHERE id = ?",
            (value, int(secret), existing["id"]),
        )
    else:
        vid = generate_id("evar")
        conn.execute(
            "INSERT INTO env_vars (id, environment_id, key, value, is_secret) VALUES (?, ?, ?, ?, ?)",
            (vid, env_row["id"], key, value, int(secret)),
        )
    conn.commit()
    display_val = "********" if secret else value
    console.print(f"[green]✓[/green] {key} = {display_val}")


@env_group.command("list")
@click.argument("env_name", required=False)
def env_list(env_name):
    """List environments and their variables."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    if env_name:
        envs = conn.execute(
            "SELECT * FROM environments WHERE project_id = ? AND name = ?",
            (proj["id"], env_name),
        ).fetchall()
        if not envs:
            console.print(f'[red]Environment "{env_name}" not found. Run: qaclan env create {env_name}[/red]')
            return
    else:
        envs = conn.execute(
            "SELECT * FROM environments WHERE project_id = ? ORDER BY name",
            (proj["id"],),
        ).fetchall()
    if not envs:
        console.print("No environments. Run: [bold]qaclan env create <name>[/bold]")
        return
    console.print(f"Environments — {proj['name']}")
    for env_row in envs:
        console.print(f"[bold]{env_row['name']}[/bold]")
        variables = conn.execute(
            "SELECT * FROM env_vars WHERE environment_id = ? ORDER BY key",
            (env_row["id"],),
        ).fetchall()
        if not variables:
            console.print("  (no variables)")
        for v in variables:
            display_val = "********" if v["is_secret"] else v["value"]
            console.print(f"  {v['key']}   {display_val}")


@env_group.command("delete")
@click.argument("env_name")
def env_delete(env_name):
    """Delete an environment."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()
    env_row = conn.execute(
        "SELECT * FROM environments WHERE project_id = ? AND name = ?",
        (proj["id"], env_name),
    ).fetchone()
    if not env_row:
        console.print(f'[red]Environment "{env_name}" not found. Run: qaclan env create {env_name}[/red]')
        return
    if not click.confirm(f"Delete environment '{env_name}' and all its variables?"):
        return
    conn.execute("DELETE FROM env_vars WHERE environment_id = ?", (env_row["id"],))
    conn.execute("DELETE FROM environments WHERE id = ?", (env_row["id"],))
    conn.commit()
    console.print(f"[green]✓[/green] Environment deleted: {env_name}")
