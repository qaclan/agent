from dotenv import load_dotenv
load_dotenv()

import click
import os
import subprocess
import sys

from cli._version import __version__ as _BAKED_VERSION
from cli.db import init_db
from cli.commands.project import project
from cli.commands.env import env_group
from cli.commands.status import status
from cli.commands.runs import runs_group
from cli.commands.web import web
from cli.commands.api import api
from cli.commands.auth import login, logout, require_auth
from cli.commands.pull import pull


def _get_version():
    """Return baked version; fall back to `git describe` in dev mode."""
    if _BAKED_VERSION != "0.0.0+dev":
        return _BAKED_VERSION
    try:
        repo_root = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(
            ["git", "-C", repo_root, "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            v = out.stdout.strip()
            return v[1:] if v.startswith("v") else v
    except Exception:
        pass
    return _BAKED_VERSION


@click.group()
@click.version_option(
    version=_get_version(),
    prog_name="qaclan",
    message="%(prog)s %(version)s",
)
def qaclan():
    """QAClan — QA test management and execution CLI."""
    init_db()


@qaclan.command()
def version():
    """Print the qaclan version."""
    click.echo(f"qaclan {_get_version()}")


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
    """Force a full resync: re-enqueue every local entity then drain the queue."""
    require_auth()
    from cli.config import get_active_project_id
    from cli.sync_queue import enqueue_all, flush_sync, queue_depth
    from rich.console import Console
    console = Console()

    if push_all_projects:
        project_ids = None
    else:
        pid = get_active_project_id()
        if pid:
            project_ids = [pid]
        else:
            console.print("[yellow]No active project. Pushing all projects...[/yellow]")
            project_ids = None

    enqueue_all(project_ids)
    total = queue_depth()
    if total == 0:
        console.print("[yellow]No pending items to push.[/yellow]")
        return

    console.print(f"[bold]Pushing {total} pending items...[/bold]")
    flush_sync(deadline=60)
    remaining = queue_depth()
    if remaining == 0:
        console.print("[green]✓ Push complete[/green]")
    else:
        console.print(f"[yellow]⚠ {remaining} item(s) still pending — will retry in background[/yellow]")


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

    # Start the background sync-queue drainer (best-effort)
    from cli.config import get_auth_key
    if get_auth_key():
        from cli.sync_queue import start_worker, trigger_now
        start_worker()
        trigger_now()

    app = create_app()
    url = f'http://localhost:{port}'
    console.print(f'[green]QAClan UI running at {url}[/green] — Press Ctrl+C to stop')
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)


@qaclan.command()
@click.option("--path-only", is_flag=True, help="Move binary + add to PATH only, skip runtime deps")
@click.option("--runtime-only", is_flag=True, help="Install runtime deps only, skip PATH/binary move")
@click.option("--no-path", is_flag=True, help="Skip PATH step (binary already on PATH)")
@click.option("--no-move", is_flag=True, help="Don't relocate binary, only add current location to PATH")
@click.option("--no-chromium", is_flag=True, help="Skip Chromium install (faster, for CI)")
@click.option("--force", is_flag=True, help="Re-run all steps even if already initialized")
def setup(path_only, runtime_only, no_path, no_move, no_chromium, force):
    """Provision isolated runtime under ~/.qaclan/runtime/ and add binary to PATH."""
    from rich.console import Console
    from cli import runtime_setup as rs

    console = Console()

    if path_only and runtime_only:
        console.print("[red]Cannot combine --path-only and --runtime-only.[/red]")
        sys.exit(2)

    do_path = not (runtime_only or no_path)
    do_runtime = not path_only

    if do_path:
        console.print("[bold]Configuring PATH...[/bold]")
        try:
            target = rs.move_binary_to_bin_dir() if not no_move else None
            if target:
                console.print(f"  Copied binary to: {target}")
            elif not no_move:
                console.print("  Binary already in place (skip move).")

            if sys.platform == "win32":
                changed = rs.add_to_path_windows()
                if changed:
                    console.print(f"  Added {rs.BIN_DIR} to user PATH (HKCU). Restart terminal.")
                else:
                    console.print("  PATH already contains ~/.qaclan/bin (skip).")
            else:
                changed = rs.add_to_path_unix()
                rc = rs.detect_rc_file()
                if changed:
                    console.print(f"  Appended PATH export to {rc}. Run: source {rc}")
                else:
                    console.print(f"  {rc} already references ~/.qaclan/bin (skip).")
        except Exception as e:
            console.print(f"[red]PATH setup failed:[/red] {e}")
            sys.exit(1)

    if do_runtime:
        console.print("[bold]Initializing runtime (Node + Python deps)...[/bold]")
        try:
            if rs.write_package_json():
                console.print(f"  Wrote {rs.PACKAGE_JSON_PATH}")
            else:
                console.print("  package.json already current (skip).")

            if rs.npm_install(force=force):
                console.print(f"  Installed Node deps in {rs.NODE_MODULES}")
            else:
                console.print("  node_modules already present (skip).")

            if rs.create_venv(force=force):
                console.print(f"  Created venv at {rs.VENV_DIR}")
            else:
                console.print("  venv already present (skip).")

            if rs.venv_pip_install(force=force):
                console.print(f"  Installed playwright=={rs.PINNED_PLAYWRIGHT_VERSION} into venv")
            else:
                console.print(f"  playwright=={rs.PINNED_PLAYWRIGHT_VERSION} already in venv (skip).")

            if not no_chromium:
                if rs.install_chromium(force=force):
                    console.print(f"  Installed Chromium to {rs.BROWSERS_DIR}")
                else:
                    console.print("  Chromium already present (skip).")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Runtime setup failed:[/red] command exited {e.returncode}")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Runtime setup failed:[/red] {e}")
            sys.exit(1)

    console.print("[green]✓ Setup complete.[/green]")


@qaclan.command("reset-runtime")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def reset_runtime(yes):
    """Remove ~/.qaclan/runtime/ so `qaclan setup` can rebuild from scratch.

    Wipes Node deps, Python venv, and Chromium. Keeps DB, scripts, config,
    and binary. Useful when runtime is corrupted or after a Playwright bump.
    """
    import shutil
    from rich.console import Console
    from cli import runtime_setup as rs

    console = Console()

    if not rs.RUNTIME_DIR.exists():
        console.print("[yellow]Nothing to remove — ~/.qaclan/runtime/ does not exist.[/yellow]")
        return

    if not yes:
        console.print("[bold red]This will permanently delete the isolated runtime:[/bold red]")
        console.print(f"  • Node deps ({rs.NODE_MODULES})")
        console.print(f"  • Python venv ({rs.VENV_DIR})")
        console.print(f"  • Chromium ({rs.BROWSERS_DIR})")
        console.print(f"  • Path: {rs.RUNTIME_DIR}")
        console.print("[dim]DB, scripts, config, and binary are kept.[/dim]")
        if not click.confirm("\nProceed?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    shutil.rmtree(rs.RUNTIME_DIR)
    console.print("[green]✓ Runtime removed.[/green] Run [bold]qaclan setup --runtime-only[/bold] to rebuild.")


@qaclan.command("_pw-install", hidden=True)
def pw_install():
    """Install Playwright browsers (used by install script)."""
    import subprocess
    import shutil
    from cli.runtime import is_frozen_binary, is_path_in_temp
    # In Nuitka binary builds, the bundled Node driver segfaults — use system playwright
    if is_frozen_binary():
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
    if is_path_in_temp(driver_executable):
        click.echo("Error: Cannot use bundled Playwright driver. Install playwright globally: npm i -g playwright", err=True)
        return
    subprocess.run(
        [driver_executable, driver_cli, "install", "chromium"],
        env=get_driver_env(),
    )


if __name__ == "__main__":
    qaclan()
