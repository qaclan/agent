import json
import logging
import os
import shutil
import subprocess
import tempfile

import click
from rich.console import Console

from cli.config import get_active_project, SCRIPTS_DIR
from cli.db import get_conn, generate_id
from cli.script_strategies import get_strategy, SUPPORTED_LANGUAGES
from cli.runtime import is_frozen_binary, is_path_in_temp, get_default_playwright_browsers_path
from datetime import datetime, timezone

console = Console()
logger = logging.getLogger("qaclan.record")

SEPARATOR = "─" * 45


def record_script(project_id, feature_id, name, url=None, url_key=None, url_key_value=None, language="python"):
    """Core recording logic shared by CLI and web UI.

    Launches Playwright codegen against the target language, wraps the output
    in a QAClan harness via the language's ScriptStrategy, and inserts a DB
    row. Returns (script_id, dest_path) on success.

    Raises ValueError for validation errors, RuntimeError for recording failures.

    If ``url_key`` + ``url_key_value`` are provided, ``page.goto()`` calls whose
    URL starts with ``url_key_value`` are rewritten to use a ``{{url_key}}``
    placeholder that the runner substitutes at execution time.
    """
    strategy = get_strategy(language)
    conn = get_conn()

    feat = conn.execute(
        "SELECT * FROM features WHERE id = ? AND project_id = ?",
        (feature_id, project_id),
    ).fetchone()
    if not feat:
        raise ValueError(f"Feature {feature_id} not found")
    if feat["channel"] != "web":
        raise ValueError(f"Feature {feature_id} is not a web feature")

    default_browsers = get_default_playwright_browsers_path()
    logger.info("Browser paths: default=%s (exists=%s), env=%s",
                default_browsers, os.path.isdir(default_browsers),
                os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "<not set>"))

    # Resolve Playwright driver: prefer Python package, fall back to npx.
    # Nuitka binary builds segfault on the bundled Node driver — skip it.
    use_npx = False
    is_frozen = is_frozen_binary()
    try:
        if is_frozen:
            raise RuntimeError("Skipping bundled driver in binary build")
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_executable, driver_cli = compute_driver_executable()
        logger.info("Python driver resolved: executable=%s (exists=%s), cli=%s",
                     driver_executable, os.path.exists(driver_executable), driver_cli)
        if is_path_in_temp(driver_executable):
            raise RuntimeError("Skipping bundled driver extracted to Nuitka temp dir")
        if not os.path.exists(driver_executable):
            raise FileNotFoundError(f"Driver executable not found at {driver_executable}")
        run_env = get_driver_env()
    except Exception as e:
        logger.warning("Python Playwright driver not available: %s", e)
        npx_path = shutil.which("npx")
        logger.info("npx lookup: %s", npx_path or "NOT FOUND")
        if npx_path:
            use_npx = True
            run_env = os.environ.copy()
        else:
            pw_path = shutil.which("playwright")
            if pw_path:
                use_npx = "playwright_cli"
                run_env = os.environ.copy()
                logger.info("Using global playwright CLI: %s", pw_path)
            else:
                logger.error("No Playwright driver found. npx=%s, playwright=%s", npx_path, pw_path)
                raise RuntimeError("Playwright not found. Install via: npm i -g playwright OR pip install playwright && playwright install chromium")

    is_docker = os.path.exists("/.dockerenv") or os.environ.get("container")
    display = os.environ.get("DISPLAY")
    logger.info("Environment: docker=%s, DISPLAY=%s", is_docker, display or "<not set>")
    if is_docker and not display:
        raise RuntimeError(
            "Recording requires a display (GUI). In Docker, use the CLI on your host machine instead: "
            "qaclan web record --feature <id> --name \"name\""
        )

    # Codegen writes to a tmp file matching the target language's extension.
    with tempfile.NamedTemporaryFile(suffix=strategy.file_extension, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        codegen_args = ["codegen", "--output", tmp_path, "--target", strategy.codegen_target]
        if use_npx == "playwright_cli":
            cmd = [shutil.which("playwright"), *codegen_args]
        elif use_npx:
            cmd = [npx_path, "playwright", *codegen_args]
        else:
            cmd = [driver_executable, driver_cli, *codegen_args]
        if url:
            cmd.append(url)

        logger.info("Launching codegen: cmd=%s", cmd)
        logger.info("Codegen env: PLAYWRIGHT_BROWSERS_PATH=%s",
                     run_env.get("PLAYWRIGHT_BROWSERS_PATH", "<not set>"))

        result = subprocess.run(cmd, env=run_env, capture_output=True, text=True)

        logger.info("Codegen exited: code=%d", result.returncode)
        if result.stdout:
            logger.info("Codegen stdout: %s", result.stdout[:2000])
        if result.stderr:
            logger.warning("Codegen stderr: %s", result.stderr[:2000])

        if result.returncode != 0:
            logger.error("Codegen failed with exit code %d. stderr: %s", result.returncode, result.stderr[:2000])

        output_exists = os.path.exists(tmp_path)
        output_size = os.path.getsize(tmp_path) if output_exists else 0
        logger.info("Output file: path=%s, exists=%s, size=%d", tmp_path, output_exists, output_size)

        if not output_exists or output_size == 0:
            detail = f"exit_code={result.returncode}"
            if result.stderr:
                detail += f", stderr={result.stderr[:500]}"
            raise RuntimeError(f"Nothing was recorded. Codegen did not produce output ({detail}). "
                               "Close the browser only after interacting with the app.")

        with open(tmp_path, "r") as f:
            raw_script = f.read()

        processed = strategy.post_process_recording(raw_script)

        var_keys_list = []
        start_url_value = url_key_value or url
        if url_key and url_key_value:
            processed = strategy.rewrite_url_template(processed, url_key_value, url_key)
            var_keys_list = [url_key]

        script_id = generate_id("script")
        dest = os.path.join(SCRIPTS_DIR, f"{script_id}{strategy.file_extension}")
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        with open(dest, "w") as f:
            f.write(processed)

        now = datetime.now(timezone.utc).isoformat()
        from cli.config import get_user_name
        created_by = get_user_name()
        conn.execute(
            "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, language, "
            "created_at, created_by, start_url_key, start_url_value, var_keys) "
            "VALUES (?, ?, ?, 'web', ?, ?, 'CLI_RECORDED', ?, ?, ?, ?, ?, ?)",
            (script_id, feature_id, project_id, name, dest, language, now, created_by,
             url_key, start_url_value, json.dumps(var_keys_list)),
        )
        conn.commit()

        from cli.sync import sync_script_to_cloud
        sync_script_to_cloud(
            script_id, name,
            feature_id=feature_id,
            project_id=project_id,
            file_content=processed,
            start_url_key=url_key,
            start_url_value=start_url_value,
            var_keys=var_keys_list,
            language=language,
        )

        return script_id, dest
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@click.command()
@click.option("--feature", "feature_id", required=True, help="Feature ID to record under")
@click.option("--name", required=True, help="Name for the recorded script")
@click.option("--url", default=None, help="Start URL for the browser")
@click.option("--language", type=click.Choice(list(SUPPORTED_LANGUAGES)), default="python",
              help="Playwright binding to record against")
def record(feature_id, name, url, language):
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
    console.print(f"Recording: [bold]{name}[/bold] ({language})")
    console.print(f"Feature:   {feat['name']}  [bold cyan]\\[WEB][/bold cyan]")
    console.print(SEPARATOR)
    console.print("Opening browser for recording...")
    console.print("Interact with the application, then close the browser when done.")

    try:
        script_id, dest = record_script(proj["id"], feature_id, name, url, language=language)
        console.print(f"\n[green]✓[/green] Script saved: {name} [{script_id}]")
        console.print(f"  Feature: {feat['name']}")
        console.print(f"  File: {dest}")
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
