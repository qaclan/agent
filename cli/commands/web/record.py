import os
import shutil
import subprocess
import tempfile

import click
from rich.console import Console

from cli.config import get_active_project, SCRIPTS_DIR
from cli.db import get_conn, generate_id
from cli.script_processor import inject_storage_state
from datetime import datetime, timezone

console = Console()

SEPARATOR = "─" * 45


def record_script(project_id, feature_id, name, url=None):
    """Core recording logic shared by CLI and web UI.

    Launches Playwright codegen, saves the recorded script, and inserts a DB record.
    Returns (script_id, dest_path) on success.
    Raises ValueError for validation errors, RuntimeError for recording failures.
    """
    conn = get_conn()

    feat = conn.execute(
        "SELECT * FROM features WHERE id = ? AND project_id = ?",
        (feature_id, project_id),
    ).fetchone()
    if not feat:
        raise ValueError(f"Feature {feature_id} not found")
    if feat["channel"] != "web":
        raise ValueError(f"Feature {feature_id} is not a web feature")

    # Point Playwright to bundled browsers only when no system browsers exist
    bundled_browsers = os.path.expanduser("~/.qaclan/browsers")
    default_browsers = os.path.expanduser("~/.cache/ms-playwright")
    if (os.path.isdir(bundled_browsers)
            and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
            and not os.path.isdir(default_browsers)):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

    # Resolve Playwright driver: prefer Python package, fall back to npx
    use_npx = False
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_executable, driver_cli = compute_driver_executable()
        if not os.path.exists(driver_executable):
            raise FileNotFoundError()
        run_env = get_driver_env()
    except Exception:
        # Binary build: Python driver not available, try npx
        npx_path = shutil.which("npx")
        if npx_path:
            use_npx = True
            run_env = os.environ.copy()
        else:
            raise RuntimeError("Playwright not found. Install via: npm i -g playwright OR pip install playwright && playwright install chromium")

    # Recording requires a headed browser with a display
    if os.path.exists("/.dockerenv") or os.environ.get("container"):
        if not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "Recording requires a display (GUI). In Docker, use the CLI on your host machine instead: "
                "qaclan web record --feature <id> --name \"name\""
            )

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if use_npx:
            cmd = [npx_path, "playwright", "codegen", "--output", tmp_path, "--target", "python"]
        else:
            cmd = [driver_executable, driver_cli, "codegen", "--output", tmp_path, "--target", "python"]
        if url:
            cmd.append(url)
        subprocess.run(cmd, env=run_env)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError("Nothing was recorded. Close the browser only after interacting with the app.")

        with open(tmp_path, "r") as f:
            raw_script = f.read()
        processed_script = inject_storage_state(raw_script)

        script_id = generate_id("script")
        dest = os.path.join(SCRIPTS_DIR, f"{script_id}.py")
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        with open(dest, "w") as f:
            f.write(processed_script)

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, created_at) "
            "VALUES (?, ?, ?, 'web', ?, ?, 'CLI_RECORDED', ?)",
            (script_id, feature_id, project_id, name, dest, now),
        )
        conn.commit()

        from cli.sync import sync_script_to_cloud
        sync_script_to_cloud(script_id, name, feature_id=feature_id, project_id=project_id, file_content=processed_script)

        return script_id, dest
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@click.command()
@click.option("--feature", "feature_id", required=True, help="Feature ID to record under")
@click.option("--name", required=True, help="Name for the recorded script")
@click.option("--url", default=None, help="Start URL for the browser")
def record(feature_id, name, url):
    """Record a web script via Playwright codegen."""
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

    console.print(SEPARATOR)
    console.print(f"Recording: [bold]{name}[/bold]")
    console.print(f"Feature:   {feat['name']}  [bold cyan]\\[WEB][/bold cyan]")
    console.print(SEPARATOR)
    console.print("Opening browser for recording...")
    console.print("Interact with the application, then close the browser when done.")

    try:
        script_id, dest = record_script(proj["id"], feature_id, name, url)
        console.print(f"\n[green]✓[/green] Script saved: {name} [{script_id}]")
        console.print(f"  Feature: {feat['name']}")
        console.print(f"  File: {dest}")
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
