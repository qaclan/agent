import os
import subprocess
import time

import click
from datetime import datetime, timezone
from rich.console import Console

from cli.config import get_active_project
from cli.db import get_conn, generate_id

console = Console()

SEPARATOR = "─" * 45


@click.command("run")
@click.option("--suite", "suite_id", required=True, help="Suite ID to run")
@click.option("--env", "env_name", default=None, help="Environment name")
@click.option("--stop-on-fail", is_flag=True, help="Stop on first failure")
def web_run(suite_id, env_name, stop_on_fail):
    """Execute a web test suite."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()

    # Load suite
    s = conn.execute(
        "SELECT * FROM suites WHERE id = ? AND project_id = ?", (suite_id, proj["id"])
    ).fetchone()
    if not s:
        console.print(f"[red]Suite {suite_id} not found. Run: qaclan web suite list[/red]")
        return
    if s["channel"] != "web":
        console.print(f"[red]Suite {suite_id} is a {s['channel'].upper()} suite. Use: qaclan {s['channel']} run[/red]")
        return

    # Load suite items
    items = conn.execute(
        "SELECT si.order_index, sc.id as script_id, sc.name as script_name, sc.file_path "
        "FROM suite_items si JOIN scripts sc ON si.script_id = sc.id "
        "WHERE si.suite_id = ? ORDER BY si.order_index",
        (suite_id,),
    ).fetchall()
    if not items:
        console.print(
            f"[red]Suite has no scripts. Add one: qaclan web suite add --suite {suite_id} --script <id>[/red]"
        )
        return

    # Load environment
    env_vars_dict = {}
    environment_id = None
    if env_name:
        env_row = conn.execute(
            "SELECT * FROM environments WHERE project_id = ? AND name = ?",
            (proj["id"], env_name),
        ).fetchone()
        if not env_row:
            console.print(f'[red]Environment "{env_name}" not found. Run: qaclan env create {env_name}[/red]')
            return
        environment_id = env_row["id"]
        variables = conn.execute(
            "SELECT key, value FROM env_vars WHERE environment_id = ?", (env_row["id"],)
        ).fetchall()
        for v in variables:
            env_vars_dict[v["key"]] = v["value"]

    # Create suite run
    run_id = generate_id("run")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at) "
        "VALUES (?, ?, ?, ?, 'web', 'RUNNING', ?, ?)",
        (run_id, suite_id, proj["id"], environment_id, len(items), now),
    )
    conn.commit()

    total = len(items)
    passed = 0
    failed = 0
    skipped = 0
    failed_scripts = []
    run_start = time.time()
    stopped = False

    for i, item in enumerate(items):
        if stopped:
            # Mark remaining as SKIPPED
            srun_id = generate_id("srun")
            script_now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, 'SKIPPED', ?, ?)",
                (srun_id, run_id, item["script_id"], item["order_index"], script_now, script_now),
            )
            skipped += 1
            console.print(f"[{i+1}/{total}] {item['script_name']}...      [yellow]⊘ SKIPPED[/yellow]")
            continue

        console.print(f"[{i+1}/{total}] {item['script_name']}...", end="")

        srun_id = generate_id("srun")
        script_start = time.time()
        script_now = datetime.now(timezone.utc).isoformat()

        env = os.environ.copy()
        env.update(env_vars_dict)

        try:
            result = subprocess.run(
                ["python", item["file_path"]],
                capture_output=True,
                text=True,
                env=env,
            )
            duration_ms = int((time.time() - script_start) * 1000)
            duration_s = duration_ms / 1000
            finished_at = datetime.now(timezone.utc).isoformat()

            if result.returncode == 0:
                status = "PASSED"
                passed += 1
                console.print(f"      [green]✓ PASSED[/green] ({duration_s:.1f}s)")
            else:
                status = "FAILED"
                failed += 1
                error_msg = result.stderr.strip().split("\n")[-1] if result.stderr.strip() else "Non-zero exit code"
                failed_scripts.append({"name": item["script_name"], "error": error_msg})
                console.print(f"      [red]✗ FAILED[/red] ({duration_s:.1f}s)")
                if stop_on_fail:
                    stopped = True

            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, duration_ms, "
                "error_message, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (srun_id, run_id, item["script_id"], item["order_index"], status, duration_ms,
                 error_msg if status == "FAILED" else None, script_now, finished_at),
            )
        except Exception as e:
            duration_ms = int((time.time() - script_start) * 1000)
            duration_s = duration_ms / 1000
            finished_at = datetime.now(timezone.utc).isoformat()
            failed += 1
            error_msg = str(e)
            failed_scripts.append({"name": item["script_name"], "error": error_msg})
            console.print(f"      [red]✗ FAILED[/red] ({duration_s:.1f}s)")
            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, duration_ms, "
                "error_message, started_at, finished_at) VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?)",
                (srun_id, run_id, item["script_id"], item["order_index"], duration_ms,
                 error_msg, script_now, finished_at),
            )
            if stop_on_fail:
                stopped = True

    # Finalize suite run
    total_duration = time.time() - run_start
    final_status = "PASSED" if failed == 0 and skipped == 0 else "FAILED"
    finished_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE suite_runs SET status = ?, passed = ?, failed = ?, skipped = ?, finished_at = ? WHERE id = ?",
        (final_status, passed, failed, skipped, finished_at, run_id),
    )

    # Update suite metadata
    conn.execute(
        "UPDATE suites SET last_run_at = ?, last_run_status = ? WHERE id = ?",
        (finished_at, final_status, suite_id),
    )
    conn.execute(
        "UPDATE suites SET first_run_at = ? WHERE id = ? AND first_run_at IS NULL",
        (finished_at, suite_id),
    )
    conn.commit()

    # Print summary
    console.print(f"\n{SEPARATOR}")
    console.print(f"Run complete: {s['name']}  [bold cyan]\\[WEB][/bold cyan]")
    status_color = "green" if final_status == "PASSED" else "red"
    console.print(f"Status: [{status_color}]{final_status}[/{status_color}]")
    console.print(f"Total: {total}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
    console.print(f"Duration: {total_duration:.1f}s")

    if failed_scripts:
        console.print("\nFailed scripts:")
        for fs in failed_scripts:
            console.print(f"  [red]✗[/red] {fs['name']}")
            console.print(f"    Error: {fs['error']}")

    console.print(f"\nRun ID: {run_id}")
