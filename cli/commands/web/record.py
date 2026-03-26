import os
import shutil
import subprocess
import tempfile

import click
from rich.console import Console

from cli.config import get_active_project, SCRIPTS_DIR
from cli.db import get_conn, generate_id
from datetime import datetime, timezone

console = Console()

SEPARATOR = "─" * 45


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
    if feat["channel"] != "web":
        console.print(f"[red]Feature {feature_id} is not a web feature.[/red]")
        return

    if shutil.which("playwright") is None:
        console.print(
            "[red]Playwright not found. Run: pip install playwright && playwright install chromium[/red]"
        )
        return

    console.print(SEPARATOR)
    console.print(f"Recording: [bold]{name}[/bold]")
    console.print(f"Feature:   {feat['name']}  [bold cyan]\\[WEB][/bold cyan]")
    console.print(SEPARATOR)
    console.print("Opening browser for recording...")
    console.print("Interact with the application, then close the browser when done.")

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = ["playwright", "codegen", "--output", tmp_path, "--target", "python"]
        if url:
            cmd.append(url)
        subprocess.run(cmd)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            console.print(
                "[red]Nothing was recorded. Close the browser only after interacting with the app.[/red]"
            )
            return

        script_id = generate_id("script")
        dest = os.path.join(SCRIPTS_DIR, f"{script_id}.py")
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        shutil.copy2(tmp_path, dest)

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, created_at) "
            "VALUES (?, ?, ?, 'web', ?, ?, 'CLI_RECORDED', ?)",
            (script_id, feature_id, proj["id"], name, dest, now),
        )
        conn.commit()

        console.print(f"\n[green]✓[/green] Script saved: {name} [{script_id}]")
        console.print(f"  Feature: {feat['name']}")
        console.print(f"  File: {dest}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
