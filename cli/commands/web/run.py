import os
import re
import time
import traceback

import click
from datetime import datetime, timezone
from rich.console import Console

from cli.config import get_active_project
from cli.db import get_conn, generate_id

console = Console()

SEPARATOR = "─" * 45


def _extract_test_actions(script_path):
    """Extract test action lines from a Playwright codegen script.

    Returns the lines between 'page = context.new_page()' and 'page.close()'
    (exclusive), dedented to top level.
    """
    with open(script_path, "r") as f:
        lines = f.readlines()

    actions = []
    capturing = False
    base_indent = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("page = context.new_page()"):
            capturing = True
            continue

        if capturing and stripped.startswith("page.close()"):
            break

        if capturing:
            # Skip empty lines and comment separators
            if not stripped or stripped.startswith("# ---"):
                continue
            # Skip storage state lines
            if "_qc_state" in stripped or "context.storage_state" in stripped:
                continue
            # Determine base indentation from first real line
            if base_indent is None:
                base_indent = len(line) - len(line.lstrip())
            # Dedent relative to base
            current_indent = len(line) - len(line.lstrip())
            relative_indent = max(0, current_indent - base_indent)
            actions.append(" " * relative_indent + stripped)

    return "\n".join(actions)


def _patch_actions(actions_src):
    """Apply runtime patches: timeout, networkidle waits."""
    # Add networkidle wait after goto
    actions_src = re.sub(
        r'(page\.goto\([^)]+\))',
        r'\1\npage.wait_for_load_state("networkidle")',
        actions_src,
    )
    # Add networkidle wait after click
    actions_src = re.sub(
        r'(\.click\(\))',
        r'\1\npage.wait_for_load_state("networkidle")',
        actions_src,
    )
    return actions_src


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

    # Inject env vars into current process for scripts that read os.environ
    for k, v in env_vars_dict.items():
        os.environ[k] = v

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

    # Storage state file for session persistence across runs
    storage_state_path = os.path.join(os.path.expanduser("~/.qaclan"), "storage_state.json")

    # Point Playwright to bundled browsers if they exist
    bundled_browsers = os.path.expanduser("~/.qaclan/browsers")
    if os.path.isdir(bundled_browsers) and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

    # Launch ONE shared browser for the entire suite
    from playwright.sync_api import sync_playwright, expect as pw_expect

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=storage_state_path if os.path.exists(storage_state_path) else None
        )

        for i, item in enumerate(items):
            if stopped:
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

            try:
                # Extract and patch test actions
                actions_src = _extract_test_actions(item["file_path"])
                actions_src = _patch_actions(actions_src)

                # Create a new page in the shared context
                page = context.new_page()
                page.set_default_timeout(30000)

                # Execute test actions with page, context, and expect in scope
                exec(actions_src, {
                    "page": page,
                    "context": context,
                    "expect": pw_expect,
                    "re": re,
                    "os": os,
                })

                page.wait_for_timeout(2000)  # Allow JS to persist session to localStorage
                page.close()

                duration_ms = int((time.time() - script_start) * 1000)
                duration_s = duration_ms / 1000
                finished_at = datetime.now(timezone.utc).isoformat()

                status = "PASSED"
                passed += 1
                console.print(f"      [green]✓ PASSED[/green] ({duration_s:.1f}s)")

                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, duration_ms, "
                    "error_message, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"], status, duration_ms,
                     None, script_now, finished_at),
                )
            except Exception as e:
                # Close page if it was opened
                try:
                    page.close()
                except Exception:
                    pass

                duration_ms = int((time.time() - script_start) * 1000)
                duration_s = duration_ms / 1000
                finished_at = datetime.now(timezone.utc).isoformat()
                failed += 1
                error_msg = traceback.format_exc()
                failed_scripts.append({"name": item["script_name"], "error": str(e)})
                console.print(f"      [red]✗ FAILED[/red] ({duration_s:.1f}s)")

                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, duration_ms, "
                    "error_message, started_at, finished_at) VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"], duration_ms,
                     error_msg, script_now, finished_at),
                )
                if stop_on_fail:
                    stopped = True

        # Save storage state for session persistence
        context.storage_state(path=storage_state_path)

        # Close shared browser
        context.close()
        browser.close()

    # Clean up injected env vars
    for k in env_vars_dict:
        os.environ.pop(k, None)

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

    # Sync run to cloud
    from cli.sync import sync_run_to_cloud
    script_run_rows = conn.execute(
        "SELECT sr.script_id, s.name as script_name, sr.status, sr.duration_ms, sr.error_message, sr.order_index "
        "FROM script_runs sr JOIN scripts s ON sr.script_id = s.id "
        "WHERE sr.suite_run_id = ? ORDER BY sr.order_index",
        (run_id,),
    ).fetchall()
    sync_run_to_cloud(
        run_id=run_id,
        suite_id=suite_id,
        status=final_status,
        started_at=now,
        completed_at=finished_at,
        duration_ms=int(total_duration * 1000),
        project_id=proj["id"],
        script_results=[
            {
                "script_id": r["script_id"],
                "script_name": r["script_name"],
                "status": r["status"].lower(),
                "duration_ms": r["duration_ms"] or 0,
                "error_output": r["error_message"],
                "order_index": r["order_index"],
            }
            for r in script_run_rows
        ],
    )

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
