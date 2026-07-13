import json
import os
import click
from datetime import datetime, timezone
from rich.console import Console

from cli.config import get_auth_key, set_active_project_id, get_active_project_id, SCRIPTS_DIR
from cli.db import get_conn, generate_id
from cli import api
from cli.script_strategies import get_strategy, SUPPORTED_LANGUAGES

console = Console()


@click.command()
def pull():
    """Download team workspace from cloud."""
    key = get_auth_key()
    if not key:
        console.print("[red]Not logged in. Run: qaclan login[/red]")
        return
    console.print("[dim]Pulling workspace from cloud...[/dim]")
    try:
        counts = pull_workspace()
    except Exception as e:
        console.print(f"[red]Pull failed: {e}[/red]")
        return
    total = sum(counts.values())
    if total == 0:
        console.print("\n[dim]Everything up to date — nothing new to pull.[/dim]")
    else:
        console.print(
            f"\n[bold]Pulled:[/bold] {counts['projects']} projects, {counts['features']} features, "
            f"{counts['scripts']} scripts, {counts['suites']} suites, "
            f"{counts['environments']} environments, {counts['env_vars']} env vars"
        )


def pull_workspace():
    """Download workspace from cloud and merge into local DB. Returns counts dict.
    Raises on network/server error."""
    key = get_auth_key()
    if not key:
        raise RuntimeError("Not logged in")

    data = api.pull_workspace(key)

    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()

    # Track cloud_id -> local_id mappings for resolving foreign keys
    project_map = {}    # cloud project id -> local project id
    feature_map = {}    # cloud feature id -> local feature id
    suite_map = {}      # cloud suite id -> local suite id
    script_map = {}     # cloud script cli_script_id -> local script id
    env_map = {}        # cloud environment id -> local environment id
    collection_map = {} # cloud api_collection id -> local api_collection id
    folder_map = {}     # cloud api_folder id -> local api_folder id

    counts = {
        "projects": 0, "features": 0, "scripts": 0, "suites": 0, "environments": 0, "env_vars": 0,
        "api_collections": 0, "api_folders": 0, "api_requests": 0, "collection_vars": 0,
    }

    # 1. Projects
    for p in data.get("projects", []):
        cloud_id = p["id"]
        existing = conn.execute("SELECT id FROM projects WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE projects SET name = ? WHERE id = ?", (p["name"], existing["id"]))
            project_map[cloud_id] = existing["id"]
        else:
            local_id = generate_id("proj")
            conn.execute(
                "INSERT INTO projects (id, name, created_at, cloud_id) VALUES (?, ?, ?, ?)",
                (local_id, p["name"], now, cloud_id),
            )
            project_map[cloud_id] = local_id
            counts["projects"] += 1
            console.print(f"  [green]✓[/green] Project: {p['name']}")

    # 2. Features
    for f in data.get("features", []):
        cloud_id = f["id"]
        existing = conn.execute("SELECT id FROM features WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE features SET name = ? WHERE id = ?", (f["name"], existing["id"]))
            feature_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(f["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("feat")
            conn.execute(
                "INSERT INTO features (id, project_id, channel, name, created_at, cloud_id) VALUES (?, ?, 'web', ?, ?, ?)",
                (local_id, local_project_id, f["name"], now, cloud_id),
            )
            feature_map[cloud_id] = local_id
            counts["features"] += 1
            console.print(f"  [green]✓[/green] Feature: {f['name']}")

    # 3. Scripts (need feature_id and project_id resolved)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    for s in data.get("scripts", []):
        cloud_id = s["id"]
        # Pulled scripts inherit the cloud row's language. Default to python
        # for back-compat with older cloud rows that pre-date the column.
        language = (s.get("language") or "python").strip()
        if language not in SUPPORTED_LANGUAGES:
            console.print(f"  [yellow]⚠[/yellow] Script skipped (unsupported language '{language}'): {s['name']}")
            continue
        start_url_key: str = s.get("start_url_key")
        start_url_value: str = s.get("start_url_value")
        # var_keys: list[str] = s.get("var_keys") or []
        # var_keys: str =  "[" + ",".join(s.get("var_keys") or []) + "]"
        var_keys: str = json.dumps(s.get("var_keys") or [], separators=(",", ":"))

        ext = get_strategy(language).file_extension
        existing = conn.execute("SELECT id, file_path FROM scripts WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            # Update name and file content and start_url_key, start_url_value and var_keys also.
            conn.execute("UPDATE scripts SET name = ?, start_url_key= ?, start_url_value = ?, var_keys = ? WHERE id = ?", 
                         (s["name"], start_url_key, start_url_value, var_keys, existing["id"]))
            file_content = s.get("file_content")
            if file_content and existing["file_path"]:
                with open(existing["file_path"], "w", encoding="utf-8") as fp:
                    fp.write(file_content)
            script_map[s.get("cli_script_id", cloud_id)] = existing["id"]
        else:
            local_feature_id = feature_map.get(s.get("feature_id"))
            local_project_id = project_map.get(s.get("project_id"))
            if not local_feature_id or not local_project_id:
                console.print(f"  [yellow]⚠[/yellow] Script skipped (missing parent): {s['name']}")
                continue
            file_content = s.get("file_content")
            if not file_content:
                console.print(f"  [yellow]⚠[/yellow] Script skipped (no content): {s['name']}")
                continue
            local_id = generate_id("script")
            file_path = os.path.join(SCRIPTS_DIR, f"{local_id}{ext}")
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write(file_content)
            created_by = s.get("created_by")
            conn.execute(
                "INSERT INTO scripts (id, feature_id, project_id, channel, name, file_path, source, language, created_at, cloud_id, created_by, start_url_key, start_url_value, var_keys) "
                "VALUES (?, ?, ?, 'web', ?, ?, 'PULLED', ?, ?, ?, ?, ?, ?, ?)",
                (local_id, local_feature_id, local_project_id, s["name"], file_path, language, now, cloud_id, created_by, start_url_key, start_url_value, var_keys),
            )
            script_map[s.get("cli_script_id", cloud_id)] = local_id
            counts["scripts"] += 1
            console.print(f"  [green]✓[/green] Script: {s['name']}")

    # 3b. API collections
    for c in data.get("api_collections", []):
        cloud_id = c["id"]
        existing = conn.execute("SELECT id FROM api_collections WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE api_collections SET name = ?, description = ?, env_name = ?, auth_type = ?, "
                "auth_config = ?, order_index = ? WHERE id = ?",
                (c["name"], c.get("description"), c.get("env_name"), c.get("auth_type", "none"),
                 json.dumps(c.get("auth_config", {})), c.get("order_index", 0), existing["id"]),
            )
            collection_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(c["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("apicol")
            conn.execute(
                "INSERT INTO api_collections (id, project_id, name, description, env_name, auth_type, "
                "auth_config, order_index, created_at, cloud_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_id, local_project_id, c["name"], c.get("description"), c.get("env_name"),
                 c.get("auth_type", "none"), json.dumps(c.get("auth_config", {})),
                 c.get("order_index", 0), now, cloud_id),
            )
            collection_map[cloud_id] = local_id
            counts["api_collections"] += 1
            console.print(f"  [green]✓[/green] API collection: {c['name']}")

    # 3c. API folders — self-referential tree, resolve parents before children.
    # Repeatedly sweep the pulled list, inserting any folder whose parent is
    # already resolved (or has none), until a full pass makes no progress.
    pending_folders = list(data.get("api_folders", []))
    while pending_folders:
        progressed = False
        still_pending = []
        for f in pending_folders:
            cloud_id = f["id"]
            parent_cloud_id = f.get("parent_folder_id")
            if parent_cloud_id and parent_cloud_id not in folder_map:
                existing_parent = conn.execute(
                    "SELECT id FROM api_folders WHERE cloud_id = ?", (parent_cloud_id,)
                ).fetchone()
                if existing_parent:
                    folder_map[parent_cloud_id] = existing_parent["id"]
                else:
                    still_pending.append(f)
                    continue
            local_parent_id = folder_map.get(parent_cloud_id) if parent_cloud_id else None
            existing = conn.execute("SELECT id FROM api_folders WHERE cloud_id = ?", (cloud_id,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE api_folders SET name = ?, order_index = ?, parent_folder_id = ? WHERE id = ?",
                    (f["name"], f.get("order_index", 0), local_parent_id, existing["id"]),
                )
                folder_map[cloud_id] = existing["id"]
            else:
                local_project_id = project_map.get(f.get("project_id"))
                local_collection_id = collection_map.get(f.get("collection_id"))
                if not local_project_id or not local_collection_id:
                    continue
                local_id = generate_id("apifold")
                conn.execute(
                    "INSERT INTO api_folders (id, project_id, collection_id, parent_folder_id, name, "
                    "order_index, created_at, cloud_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (local_id, local_project_id, local_collection_id, local_parent_id,
                     f["name"], f.get("order_index", 0), now, cloud_id),
                )
                folder_map[cloud_id] = local_id
                counts["api_folders"] += 1
                console.print(f"  [green]✓[/green] API folder: {f['name']}")
            progressed = True
        if not progressed:
            for f in still_pending:
                console.print(f"  [yellow]⚠[/yellow] API folder skipped (unresolved parent): {f.get('name')}")
            break
        pending_folders = still_pending

    # 3d. API requests
    for r in data.get("api_requests", []):
        cloud_id = r["id"]
        local_project_id = project_map.get(r.get("project_id"))
        local_feature_id = feature_map.get(r.get("feature_id")) if r.get("feature_id") else None
        local_collection_id = collection_map.get(r.get("collection_id")) if r.get("collection_id") else None
        local_folder_id = folder_map.get(r.get("folder_id")) if r.get("folder_id") else None
        row_values = (
            r["name"], r.get("method", "GET"), r.get("url", ""),
            json.dumps(r.get("headers", [])), json.dumps(r.get("params", [])),
            json.dumps(r.get("path_params", [])), r.get("body_type"), r.get("body"),
            r.get("auth_type", "none"), json.dumps(r.get("auth_config", {})),
            r.get("pre_script"), r.get("pre_lang", "js"),
            json.dumps(r["pre_extractor"]) if r.get("pre_extractor") else None,
            r.get("post_script"), r.get("post_lang", "js"),
            json.dumps(r["post_extractor"]) if r.get("post_extractor") else None,
            json.dumps(r["request_schema"]) if r.get("request_schema") else None,
            json.dumps(r["response_schema"]) if r.get("response_schema") else None,
            json.dumps(r.get("assertions", [])),
            1 if r.get("follow_redirects", True) else 0, r.get("timeout_ms", 30000),
            1 if r.get("include_in_docs", True) else 0, r.get("order_index", 0),
        )
        existing = conn.execute("SELECT id FROM api_requests WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE api_requests SET name=?, method=?, url=?, headers=?, params=?, path_params=?, "
                "body_type=?, body=?, auth_type=?, auth_config=?, pre_script=?, pre_lang=?, pre_extractor=?, "
                "post_script=?, post_lang=?, post_extractor=?, request_schema=?, response_schema=?, "
                "assertions=?, follow_redirects=?, timeout_ms=?, include_in_docs=?, order_index=?, "
                "feature_id=?, collection_id=?, folder_id=? WHERE id=?",
                row_values + (local_feature_id, local_collection_id, local_folder_id, existing["id"]),
            )
        else:
            if not local_project_id:
                console.print(f"  [yellow]⚠[/yellow] API request skipped (missing project): {r.get('name')}")
                continue
            local_id = generate_id("apireq")
            conn.execute(
                "INSERT INTO api_requests (id, project_id, feature_id, collection_id, folder_id, name, "
                "method, url, headers, params, path_params, body_type, body, auth_type, auth_config, "
                "pre_script, pre_lang, pre_extractor, post_script, post_lang, post_extractor, "
                "request_schema, response_schema, assertions, follow_redirects, timeout_ms, "
                "include_in_docs, order_index, created_at, cloud_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_id, local_project_id, local_feature_id, local_collection_id, local_folder_id)
                + row_values + (now, cloud_id),
            )
            counts["api_requests"] += 1
            console.print(f"  [green]✓[/green] API request: {r.get('name')}")

    # 3e. Collection variables (full-replace-list semantics, like env_vars)
    for v in data.get("collection_vars", []):
        local_collection_id = collection_map.get(v["collection_id"])
        if not local_collection_id:
            continue
        existing = conn.execute(
            "SELECT id FROM collection_vars WHERE collection_id = ? AND key = ?",
            (local_collection_id, v["key"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE collection_vars SET initial_value = ? WHERE id = ?",
                (v["initial_value"], existing["id"]),
            )
        else:
            local_id = generate_id("cv")
            conn.execute(
                "INSERT INTO collection_vars (id, collection_id, key, initial_value, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (local_id, local_collection_id, v["key"], v["initial_value"], now),
            )
            counts["collection_vars"] += 1

    # 4. Environments
    for e in data.get("environments", []):
        cloud_id = e["id"]
        existing = conn.execute("SELECT id FROM environments WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE environments SET name = ? WHERE id = ?", (e["name"], existing["id"]))
            env_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(e["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("env")
            conn.execute(
                "INSERT INTO environments (id, project_id, name, created_at, cloud_id) VALUES (?, ?, ?, ?, ?)",
                (local_id, local_project_id, e["name"], now, cloud_id),
            )
            env_map[cloud_id] = local_id
            counts["environments"] += 1
            console.print(f"  [green]✓[/green] Environment: {e['name']}")

    # 5. Environment variables
    for v in data.get("env_vars", []):
        local_env_id = env_map.get(v["environment_id"])
        if not local_env_id:
            continue
        existing = conn.execute(
            "SELECT id FROM env_vars WHERE environment_id = ? AND key = ?",
            (local_env_id, v["key"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE env_vars SET value = ?, is_secret = ? WHERE id = ?",
                (v["value"], 1 if v.get("is_secret") else 0, existing["id"]),
            )
        else:
            local_id = generate_id("evar")
            conn.execute(
                "INSERT INTO env_vars (id, environment_id, key, value, is_secret) VALUES (?, ?, ?, ?, ?)",
                (local_id, local_env_id, v["key"], v["value"], 1 if v.get("is_secret") else 0),
            )
            counts["env_vars"] += 1

    # 6. Suites
    for s in data.get("suites", []):
        cloud_id = s["id"]
        existing = conn.execute("SELECT id FROM suites WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute("UPDATE suites SET name = ? WHERE id = ?", (s["name"], existing["id"]))
            suite_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(s["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("suite")
            conn.execute(
                "INSERT INTO suites (id, project_id, channel, name, created_at, cloud_id) VALUES (?, ?, 'web', ?, ?, ?)",
                (local_id, local_project_id, s["name"], now, cloud_id),
            )
            suite_map[cloud_id] = local_id
            counts["suites"] += 1
            console.print(f"  [green]✓[/green] Suite: {s['name']}")

    # 7. Suite items
    for si in data.get("suite_items", []):
        local_suite_id = suite_map.get(si["suite_id"])
        local_script_id = script_map.get(si["cli_script_id"])
        if not local_suite_id or not local_script_id:
            continue
        existing = conn.execute(
            "SELECT id FROM suite_items WHERE suite_id = ? AND script_id = ?",
            (local_suite_id, local_script_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE suite_items SET order_index = ? WHERE id = ?",
                (si["order_index"], existing["id"]),
            )
        else:
            local_id = generate_id("si")
            conn.execute(
                "INSERT INTO suite_items (id, suite_id, script_id, order_index, created_at) VALUES (?, ?, ?, ?, ?)",
                (local_id, local_suite_id, local_script_id, si["order_index"], now),
            )

    conn.commit()

    # Set first pulled project as active if no active project
    if not get_active_project_id() and project_map:
        first_local_id = next(iter(project_map.values()))
        set_active_project_id(first_local_id)

    return counts


def pull_api_run_history(project_id):
    """On-demand pull of standalone collection-run history for one project.
    Not part of pull_workspace() — called lazily when the API Runs view opens.
    Returns the number of new runs inserted."""
    key = get_auth_key()
    if not key:
        raise RuntimeError("Not logged in")
    conn = get_conn()
    inserted = 0
    page = 1
    while True:
        data = api.pull_api_runs(key, page=page, per_page=50)
        runs = data.get("runs", [])
        if not runs:
            break
        for run_summary in runs:
            # Match on cli_collection_run_id (the pushing client's own local id) first —
            # api_collection_runs has no cloud_id column, so if this row was originally
            # pushed FROM this machine, its local id already equals cli_collection_run_id
            # and this avoids inserting a second, duplicate copy under the server's id.
            # Falls back to the server's id only for runs this machine never pushed itself.
            local_run_id = run_summary.get("cli_collection_run_id") or run_summary["id"]
            existing = conn.execute(
                "SELECT id FROM api_collection_runs WHERE id = ?", (local_run_id,)
            ).fetchone()
            if existing:
                continue  # runs are immutable once finished — nothing to update
            local_collection_row = conn.execute(
                "SELECT id FROM api_collections WHERE cloud_id = ?", (run_summary["collection_id"],)
            ).fetchone()
            if not local_collection_row:
                continue  # collection not pulled locally yet — skip, will retry next pull
            detail = api.pull_api_run_detail(key, run_summary["id"])
            conn.execute(
                "INSERT INTO api_collection_runs (id, project_id, collection_id, collection_name, "
                "env_name, status, total, passed, failed, error_count, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_run_id, project_id, local_collection_row["id"], run_summary["collection_name"],
                 run_summary.get("env_name"), run_summary["status"].upper(), run_summary["total"],
                 run_summary["passed"], run_summary["failed"], run_summary["error_count"],
                 run_summary["started_at"], run_summary.get("completed_at")),
            )
            for r in detail.get("request_results", []):
                local_request_row = conn.execute(
                    "SELECT id FROM api_requests WHERE cloud_id = ?", (r["cli_request_id"],)
                ).fetchone()
                if not local_request_row:
                    # Parent request not pulled locally (yet, or ever — e.g. deleted since).
                    # api_request_results.api_request_id is NOT NULL + FK-enforced
                    # (PRAGMA foreign_keys = ON, cli/db.py:20) — inserting the raw cloud
                    # request id here would raise sqlite3.IntegrityError. Skip the row
                    # instead, same as every other orphan guard in pull_workspace().
                    continue
                conn.execute(
                    "INSERT INTO api_request_results (id, collection_run_id, api_request_id, "
                    "request_name, method, url, order_index, status, status_code, response_body, "
                    "response_headers, duration_ms, assertion_results, error_message, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (generate_id("arreq"), local_run_id, local_request_row["id"],
                     r["request_name"], r.get("method"), r.get("url"), r["order_index"],
                     r["status"].upper(), r.get("status_code"), r.get("response_body"),
                     json.dumps(r["response_headers"]) if r.get("response_headers") else None,
                     r.get("duration_ms"),
                     json.dumps(r["assertion_results"]) if r.get("assertion_results") else None,
                     r.get("error_message"), r.get("started_at"), r.get("finished_at")),
                )
            inserted += 1
        if len(runs) < 50:
            break
        page += 1
    conn.commit()
    return inserted


def pull_api_docs_overlay(project_id):
    """On-demand pull of the server-computed docs cache for one project. Overlay
    semantics: only overwrite a local doc entry if the pulled last_seen_at is
    newer, so a user's own live-regenerated local docs aren't clobbered by a
    stale team snapshot. Returns the number of entries updated or inserted."""
    key = get_auth_key()
    if not key:
        raise RuntimeError("Not logged in")
    conn = get_conn()
    data = api.pull_api_docs(key, project_id)
    changed = 0
    for entry in data.get("doc_entries", []):
        existing = conn.execute(
            "SELECT id, last_seen_at FROM api_doc_entries WHERE project_id = ? AND method = ? AND path_pattern = ?",
            (project_id, entry["method"], entry["path_pattern"]),
        ).fetchone()
        if existing and existing["last_seen_at"] >= entry["last_seen_at"]:
            continue  # local copy is newer or equal — don't clobber
        if existing:
            conn.execute(
                "UPDATE api_doc_entries SET request_schema=?, response_schema=?, headers_schema=?, "
                "params_schema=?, source_request_ids=?, last_seen_at=? WHERE id=?",
                (json.dumps(entry.get("request_schema")) if entry.get("request_schema") else None,
                 json.dumps(entry.get("response_schema")) if entry.get("response_schema") else None,
                 json.dumps(entry.get("headers_schema")) if entry.get("headers_schema") else None,
                 json.dumps(entry.get("params_schema")) if entry.get("params_schema") else None,
                 json.dumps(entry.get("source_request_ids", [])), entry["last_seen_at"], existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO api_doc_entries (id, project_id, method, path_pattern, description, "
                "request_schema, response_schema, headers_schema, params_schema, source_request_ids, "
                "include_in_docs, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (generate_id("apidoc"), project_id, entry["method"], entry["path_pattern"],
                 entry.get("description"),
                 json.dumps(entry.get("request_schema")) if entry.get("request_schema") else None,
                 json.dumps(entry.get("response_schema")) if entry.get("response_schema") else None,
                 json.dumps(entry.get("headers_schema")) if entry.get("headers_schema") else None,
                 json.dumps(entry.get("params_schema")) if entry.get("params_schema") else None,
                 json.dumps(entry.get("source_request_ids", [])),
                 1 if entry.get("include_in_docs", True) else 0,
                 entry.get("first_seen_at", entry["last_seen_at"]), entry["last_seen_at"]),
            )
        changed += 1
    conn.commit()
    return changed
