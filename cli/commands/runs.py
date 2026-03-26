import click
from rich.console import Console
from rich.table import Table

from cli.config import get_active_project
from cli.db import get_conn

console = Console()


@click.group("runs", invoke_without_command=True)
@click.option("--suite", "suite_id", default=None, help="Filter by suite ID")
@click.pass_context
def runs_group(ctx, suite_id):
    """View run history."""
    if ctx.invoked_subcommand is not None:
        return
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()

    if suite_id:
        rows = conn.execute(
            "SELECT sr.id, s.name as suite_name, sr.channel, sr.status, sr.passed, sr.total, "
            "sr.started_at, sr.finished_at "
            "FROM suite_runs sr JOIN suites s ON sr.suite_id = s.id "
            "WHERE sr.project_id = ? AND sr.suite_id = ? "
            "ORDER BY sr.started_at DESC",
            (proj["id"], suite_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sr.id, s.name as suite_name, sr.channel, sr.status, sr.passed, sr.total, "
            "sr.started_at, sr.finished_at "
            "FROM suite_runs sr JOIN suites s ON sr.suite_id = s.id "
            "WHERE sr.project_id = ? "
            "ORDER BY sr.started_at DESC",
            (proj["id"],),
        ).fetchall()

    if not rows:
        console.print("No runs yet. Create a suite and run it:")
        console.print("  [bold]qaclan web suite create \"name\"[/bold]")
        console.print("  [bold]qaclan web run --suite <id> --env <name>[/bold]")
        return

    table = Table()
    table.add_column("Run ID")
    table.add_column("Suite")
    table.add_column("Channel")
    table.add_column("Status")
    table.add_column("Scripts")
    table.add_column("Started")
    table.add_column("Duration")

    for r in rows:
        scripts_col = f"{r['passed']}/{r['total']}"
        started = r["started_at"][:16].replace("T", " ") if r["started_at"] else "—"
        if r["started_at"] and r["finished_at"]:
            from datetime import datetime
            start_dt = datetime.fromisoformat(r["started_at"])
            end_dt = datetime.fromisoformat(r["finished_at"])
            dur = (end_dt - start_dt).total_seconds()
            duration = f"{dur:.1f}s"
        else:
            duration = "—"
        table.add_row(r["id"], r["suite_name"], r["channel"].upper(), r["status"], scripts_col, started, duration)

    console.print(table)


@runs_group.command("show")
@click.argument("run_id")
def run_show(run_id):
    """Show detailed results for a run."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()

    sr = conn.execute(
        "SELECT sr.*, s.name as suite_name, e.name as env_name "
        "FROM suite_runs sr "
        "JOIN suites s ON sr.suite_id = s.id "
        "LEFT JOIN environments e ON sr.environment_id = e.id "
        "WHERE sr.id = ?",
        (run_id,),
    ).fetchone()
    if not sr:
        console.print(f"[red]Run {run_id} not found. Run: qaclan runs[/red]")
        return

    status_color = "green" if sr["status"] == "PASSED" else "red"
    console.print(
        f"Run #{sr['id']} — {sr['suite_name']} — {sr['channel'].upper()} — "
        f"[{status_color}]{sr['status']}[/{status_color}]"
    )

    started = sr["started_at"][:16].replace("T", " ") if sr["started_at"] else "—"
    if sr["started_at"] and sr["finished_at"]:
        from datetime import datetime
        start_dt = datetime.fromisoformat(sr["started_at"])
        end_dt = datetime.fromisoformat(sr["finished_at"])
        dur = (end_dt - start_dt).total_seconds()
        duration = f"{dur:.1f}s"
    else:
        duration = "—"

    env_str = sr["env_name"] if sr["env_name"] else "none"
    console.print(f"Started: {started}  Duration: {duration}  Environment: {env_str}")
    console.print()

    script_runs = conn.execute(
        "SELECT scr.*, s.name as script_name "
        "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
        "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
        (run_id,),
    ).fetchall()

    for scr in script_runs:
        dur_s = f"{scr['duration_ms'] / 1000:.1f}s" if scr["duration_ms"] else "—"
        if scr["status"] == "PASSED":
            console.print(
                f"[{scr['order_index'] + 1}] {scr['script_name']}    "
                f"[green]PASSED[/green]   {dur_s}   console errors: {scr['console_errors']}"
            )
        elif scr["status"] == "FAILED":
            console.print(
                f"[{scr['order_index'] + 1}] {scr['script_name']}    "
                f"[red]FAILED[/red]   {dur_s}   console errors: {scr['console_errors']}"
            )
            if scr["error_message"]:
                console.print(f"    Error: {scr['error_message']}")
        elif scr["status"] == "SKIPPED":
            console.print(
                f"[{scr['order_index'] + 1}] {scr['script_name']}    "
                f"[yellow]SKIPPED[/yellow]"
            )
