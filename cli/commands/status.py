import click
from rich.console import Console

from cli.config import get_active_project
from cli.db import get_conn

console = Console()

SEPARATOR = "─" * 45


@click.command()
def status():
    """Show full project status."""
    proj = get_active_project(console)
    if not proj:
        return
    conn = get_conn()

    console.print(f"Project: [bold]{proj['name']}[/bold]")
    console.print(SEPARATOR)

    total_web_scripts = 0
    total_web_features = 0
    features_no_scripts = 0

    for channel in ["web", "api"]:
        console.print(f"[bold]{channel.upper()}[/bold]")
        features = conn.execute(
            "SELECT * FROM features WHERE project_id = ? AND channel = ? ORDER BY name",
            (proj["id"], channel),
        ).fetchall()

        if not features:
            console.print(
                f"No {channel.upper()} features yet. "
                f"Run `qaclan {channel} feature create \"name\"` to start.\n"
            )
            console.print(SEPARATOR)
            continue

        for feat in features:
            scripts = conn.execute(
                "SELECT id, name FROM scripts WHERE feature_id = ? ORDER BY name",
                (feat["id"],),
            ).fetchall()
            count = len(scripts)
            if channel == "web":
                total_web_features += 1
                total_web_scripts += count
                if count == 0:
                    features_no_scripts += 1

            warning = "  [yellow]⚠ no scripts recorded[/yellow]" if count == 0 else ""
            console.print(f"Feature: [bold]{feat['name']}[/bold]        {count} scripts{warning}")
            for sc in scripts:
                console.print(f"  · {sc['name']}              [{sc['id']}]")

        console.print()
        console.print(SEPARATOR)

    # Summary
    summary_parts = [f"{total_web_scripts} web scripts across {total_web_features} features."]
    if features_no_scripts > 0:
        summary_parts.append(f"{features_no_scripts} feature(s) have no scripts.")
    console.print(" ".join(summary_parts))
