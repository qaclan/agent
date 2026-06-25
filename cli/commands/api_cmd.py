from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cli.db import init_db
from cli.config import get_active_project_id

logger = logging.getLogger("qaclan.api_cmd")
console = Console()


def _require_project():
    init_db()
    pid = get_active_project_id()
    if not pid:
        console.print("[red]No active project. Run: qaclan project use <name>[/red]")
        sys.exit(1)
    return pid


def _print_request_result(r: dict):
    color = "green" if r["status"] == "PASSED" else "red"
    console.print(f"[{color}]{r['status']}[/{color}] {r.get('method','')} {r.get('url','')} → {r.get('status_code','')} ({r.get('duration_ms',0)}ms)")
    for a in r.get("assertions", []):
        mark = "✓" if a["passed"] else "✗"
        console.print(f"  {mark} {a['name']}: {a.get('message','')}")


def _print_collection_result(r: dict):
    color = "green" if r["status"] == "PASSED" else "red"
    console.print(f"[{color}]{r['status']}[/{color}] {r['passed']}/{r['total']} passed")
    for item in r.get("results", []):
        _print_request_result(item)


@click.group("api")
def api_group():
    """API testing commands."""
    pass


@api_group.command("list")
@click.option("--collection", "-c", help="Show requests inside this collection")
def api_list(collection):
    """List API collections or requests in the active project."""
    pid = _require_project()
    from web.api.services.collection_service import CollectionService
    from web.api.services.request_service import RequestService

    if collection:
        cols = CollectionService().list(pid)
        col = next((c for c in cols if c["name"] == collection), None)
        if col is None:
            console.print(f"[red]Collection '{collection}' not found[/red]")
            sys.exit(1)
        reqs = RequestService().list(pid, collection_id=col["id"])
        if not reqs:
            console.print("[yellow]No requests found in this collection.[/yellow]")
            return
        table = Table(title=f"Requests in '{collection}'", show_header=True, header_style="bold cyan")
        table.add_column("Name", style="bold")
        table.add_column("Method", width=8)
        table.add_column("URL", max_width=60)
        table.add_column("ID", style="dim")
        for r in reqs:
            method_style = {
                "GET": "green", "POST": "blue", "PUT": "yellow",
                "PATCH": "yellow", "DELETE": "red",
            }.get(r["method"], "white")
            table.add_row(
                r["name"],
                f"[{method_style}]{r['method']}[/{method_style}]",
                r["url"],
                r["id"],
            )
        console.print(table)
    else:
        cols = CollectionService().list(pid)
        if not cols:
            console.print("[yellow]No collections found.[/yellow]")
            return
        table = Table(title="Collections", show_header=True, header_style="bold cyan")
        table.add_column("Name", style="bold")
        table.add_column("Requests", justify="right")
        table.add_column("ID", style="dim")
        for c in cols:
            table.add_row(c["name"], str(c.get("request_count", 0)), c["id"])
        console.print(table)


@api_group.command("run")
@click.argument("name_or_id")
@click.option("--collection", "-c", help="Collection name (required when running full collection)")
@click.option("--env", "-e", help="Environment name")
def api_run(name_or_id, collection, env):
    """Run a single API request or all requests in a collection."""
    pid = _require_project()
    from web.api.services.runner_service import RunnerService
    from web.api.services.collection_service import CollectionService
    from web.api.services.request_service import RequestService
    svc = RunnerService()

    if collection:
        # run whole collection
        cols = CollectionService().list(pid)
        col = next((c for c in cols if c["name"] == collection or c["id"] == collection), None)
        if col is None:
            console.print(f"[red]Collection '{collection}' not found[/red]")
            sys.exit(1)
        console.print(f"[cyan]Running collection '{collection}'...[/cyan]\n")
        result = svc.run_collection(col["id"], pid, env_name=env)
        _print_collection_result(result)
    else:
        # run single request by id or name
        reqs = RequestService().list(pid)
        req = next((r for r in reqs if r["id"] == name_or_id or r["name"] == name_or_id), None)
        if req is None:
            console.print(f"[red]Request '{name_or_id}' not found[/red]")
            sys.exit(1)
        console.print(f"[cyan]Running '{req['name']}' ({req['method']} {req['url']})...[/cyan]")
        result = svc.run_request(req["id"], pid, env_name=env)
        _print_request_result(result)
        if result.get("response_body"):
            console.print("\n[bold]Response Body:[/bold]")
            try:
                parsed = json.loads(result["response_body"])
                console.print_json(json.dumps(parsed, indent=2))
            except (ValueError, TypeError):
                console.print(result["response_body"][:1000])


@api_group.command("export")
@click.argument("collection")
@click.option("--output", "-o", default=".", help="Output directory for .bru files")
def api_export(collection, output):
    """Export a collection as Bruno .bru files."""
    pid = _require_project()
    from web.api.services.collection_service import CollectionService
    from web.api.services.request_service import RequestService
    from cli.api_discovery.bruno_parser import request_to_bru

    cols = CollectionService().list(pid)
    col = next((c for c in cols if c["name"] == collection or c["id"] == collection), None)
    if col is None:
        console.print(f"[red]Collection '{collection}' not found[/red]")
        sys.exit(1)

    reqs = RequestService().list(pid, collection_id=col["id"])
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for req in reqs:
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in req["name"])
        (out_dir / f"{safe_name}.bru").write_text(request_to_bru(req), encoding="utf-8")
    console.print(f"[green]Exported {len(reqs)} requests to {out_dir}[/green]")


@api_group.command("import")
@click.argument("file_or_url")
@click.option("--format", "fmt", default="auto",
              type=click.Choice(["auto", "har", "openapi", "postman", "bruno"]),
              help="Import format (default: auto-detect)")
@click.option("--collection", default=None, help="Collection name (for HAR import)")
def api_import(file_or_url, fmt, collection):
    """Import API requests from HAR, OpenAPI, Postman, or Bruno files."""
    pid = _require_project()

    # Auto-detect format
    if fmt == "auto":
        lower = file_or_url.lower()
        if lower.startswith("http"):
            fmt = "openapi"
        elif lower.endswith(".har"):
            fmt = "har"
        elif lower.endswith(".yaml") or lower.endswith(".yml") or "openapi" in lower or "swagger" in lower:
            fmt = "openapi"
        elif lower.endswith(".bru"):
            fmt = "bruno"
        else:
            # Try to detect from file content
            try:
                content = Path(file_or_url).read_text(encoding="utf-8")
                data = json.loads(content)
                if "log" in data and "entries" in data.get("log", {}):
                    fmt = "har"
                elif "info" in data and "item" in data:
                    fmt = "postman"
                elif "openapi" in data or "swagger" in data:
                    fmt = "openapi"
                else:
                    fmt = "har"
            except (ValueError, OSError):
                fmt = "openapi"

    from web.api.services.discovery_service import DiscoveryService
    svc = DiscoveryService()

    if fmt == "har":
        content = Path(file_or_url).read_text(encoding="utf-8")
        har_json = json.loads(content)
        col_name = collection or Path(file_or_url).stem
        result = svc.import_har(pid, har_json, collection_name=col_name)
        console.print(f"[green]Imported {result['imported']} requests[/green]")

    elif fmt == "openapi":
        if file_or_url.startswith("http"):
            result = svc.import_openapi(pid, file_or_url)
        else:
            content = Path(file_or_url).read_text(encoding="utf-8")
            if file_or_url.endswith((".yaml", ".yml")):
                import yaml
                spec = yaml.safe_load(content)
            else:
                spec = json.loads(content)
            result = svc.import_openapi(pid, spec)
        console.print(f"[green]Imported {result['imported']} requests across {len(result.get('collections', []))} collections[/green]")

    elif fmt == "postman":
        content = Path(file_or_url).read_text(encoding="utf-8")
        col_json = json.loads(content)
        result = svc.import_postman(pid, col_json)
        console.print(f"[green]Imported {result['imported']} requests[/green]")

    elif fmt == "bruno":
        content = Path(file_or_url).read_text(encoding="utf-8")
        result = svc.import_bruno(pid, [{"name": Path(file_or_url).name, "content": content}])
        console.print(f"[green]Imported {result['imported']} requests[/green]")


@api_group.command("record")
@click.option("--url", default="about:blank", help="Starting URL for recording browser")
def api_record(url):
    """Launch a browser, capture API requests, then prompt to save them."""
    pid = _require_project()
    console.print(f"[cyan]Opening browser at {url}...[/cyan]")
    console.print("[yellow]Interact with the app, then close the browser window to stop recording.[/yellow]")

    import os
    from cli.api_discovery.har_parser import parse_har

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        har_file = os.path.join(tmpdir, "captured.har")

        from web.api.services.discovery_service import DiscoveryService
        DiscoveryService().record_sync(url, har_file)

        if not os.path.exists(har_file):
            console.print("[red]No HAR file captured.[/red]")
            return

        with open(har_file) as f:
            har_json = json.load(f)

        requests = parse_har(har_json)
        if not requests:
            console.print("[yellow]No API requests captured.[/yellow]")
            return

        console.print(f"\n[green]Captured {len(requests)} requests.[/green]")
        for i, r in enumerate(requests[:20]):
            console.print(f"  {i+1}. {r['method']} {r['url'][:80]}")
        if len(requests) > 20:
            console.print(f"  ... and {len(requests) - 20} more")

        col_name = click.prompt("\nCollection name to save as", default="Recorded APIs")
        save = click.confirm(f"Save {len(requests)} requests to collection '{col_name}'?", default=True)
        if save:
            from web.api.services.discovery_service import DiscoveryService
            result = DiscoveryService().import_har(pid, har_json, collection_name=col_name)
            console.print(f"[green]Saved {result['imported']} requests.[/green]")
