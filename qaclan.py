from dotenv import load_dotenv
load_dotenv()

import click
import os
import sys

from cli.db import init_db
from cli.commands.project import project
from cli.commands.env import env_group
from cli.commands.status import status
from cli.commands.runs import runs_group
from cli.commands.web import web
from cli.commands.api import api
from cli.commands.auth import login, logout, require_auth
from cli.commands.pull import pull


@click.group()
def qaclan():
    """QAClan — QA test management and execution CLI."""
    init_db()


qaclan.add_command(login, "login")
qaclan.add_command(logout, "logout")


@qaclan.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def uninstall(yes):
    """Remove all QAClan local data (~/.qaclan/)."""
    import shutil
    from rich.console import Console
    from cli.config import QACLAN_DIR

    console = Console()

    if not os.path.exists(QACLAN_DIR):
        console.print("[yellow]Nothing to remove — ~/.qaclan/ does not exist.[/yellow]")
        return

    if not yes:
        console.print(f"[bold red]This will permanently delete all local QAClan data:[/bold red]")
        console.print(f"  • Database (projects, features, suites, runs)")
        console.print(f"  • Recorded scripts")
        console.print(f"  • Config and auth credentials")
        console.print(f"  • Path: {QACLAN_DIR}")
        if not click.confirm("\nAre you sure?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    shutil.rmtree(QACLAN_DIR)
    console.print("[green]✓ All QAClan local data removed.[/green]")


# Wrap existing commands with auth gate
_original_project_invoke = project.invoke
_original_env_invoke = env_group.invoke
_original_status_invoke = status.invoke
_original_runs_invoke = runs_group.invoke
_original_web_invoke = web.invoke
_original_api_invoke = api.invoke


def _auth_wrap(original_invoke):
    def wrapped(ctx):
        require_auth()
        return original_invoke(ctx)
    return wrapped


_original_pull_invoke = pull.invoke

project.invoke = _auth_wrap(_original_project_invoke)
env_group.invoke = _auth_wrap(_original_env_invoke)
status.invoke = _auth_wrap(_original_status_invoke)
runs_group.invoke = _auth_wrap(_original_runs_invoke)
web.invoke = _auth_wrap(_original_web_invoke)
api.invoke = _auth_wrap(_original_api_invoke)
pull.invoke = _auth_wrap(_original_pull_invoke)


qaclan.add_command(project, "project")
qaclan.add_command(env_group, "env")
qaclan.add_command(status, "status")
qaclan.add_command(runs_group, "runs")
qaclan.add_command(web, "web")
qaclan.add_command(api, "api")
qaclan.add_command(pull, "pull")


# Also register `run show` at top level as `qaclan run show`
@qaclan.group("run", invoke_without_command=True)
@click.pass_context
def run_group(ctx):
    """View individual run details."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


_original_run_group_invoke = run_group.invoke


def _run_group_auth_wrap(ctx):
    require_auth()
    return _original_run_group_invoke(ctx)


run_group.invoke = _run_group_auth_wrap

from cli.commands.runs import run_show
run_group.add_command(run_show, "show")


@qaclan.command()
@click.option("--all", "push_all_projects", is_flag=True, help="Push all projects, not just the active one")
def push(push_all_projects):
    """Push all local data to the cloud server."""
    require_auth()
    from cli.config import get_active_project_id
    from cli.sync import sync_all
    from rich.console import Console
    console = Console()
    if push_all_projects:
        sync_all(project_id=None)
    else:
        project_id = get_active_project_id()
        if not project_id:
            console.print("[yellow]No active project. Pushing all projects...[/yellow]")
        sync_all(project_id=project_id)


@qaclan.command()
@click.option('--port', default=7823, help='Port to run on')
@click.option('--host', default='127.0.0.1', help='Host to bind to (use 0.0.0.0 for Docker)')
@click.option('--no-browser', is_flag=True, help='Do not open browser automatically')
def serve(port, host, no_browser):
    """Start the QAClan web UI."""
    import logging
    import webbrowser
    import threading
    from rich.console import Console
    from web.server import create_app

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console = Console()

    # Run a full sync on startup (best-effort)
    from cli.config import get_auth_key
    if get_auth_key():
        console.print('[dim]Syncing to cloud...[/dim]')
        try:
            from cli.sync import sync_all
            sync_all()
        except Exception as e:
            console.print(f'[yellow]⚠ Startup sync failed: {e}[/yellow]')

    app = create_app()
    url = f'http://localhost:{port}'
    console.print(f'[green]QAClan UI running at {url}[/green] — Press Ctrl+C to stop')
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)


@qaclan.command("_pw-install", hidden=True)
def pw_install():
    """Install Playwright browsers (used by install script)."""
    import subprocess
    import shutil
    # In Nuitka binary builds, the bundled Node driver segfaults — use system playwright
    if getattr(sys, 'frozen', False) or "/tmp/onefile_" in (sys.executable or ""):
        pw_path = shutil.which("playwright")
        if pw_path:
            subprocess.run([pw_path, "install", "chromium"])
            return
        npx_path = shutil.which("npx")
        if npx_path:
            subprocess.run([npx_path, "playwright", "install", "chromium"])
            return
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    driver_executable, driver_cli = compute_driver_executable()
    if "/tmp/onefile_" in driver_executable:
        click.echo("Error: Cannot use bundled Playwright driver. Install playwright globally: npm i -g playwright", err=True)
        return
    subprocess.run(
        [driver_executable, driver_cli, "install", "chromium"],
        env=get_driver_env(),
    )


if __name__ == "__main__":
    qaclan()
