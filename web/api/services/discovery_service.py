from __future__ import annotations
import json
import logging
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.request_repo import RequestRepo
from cli.sync_queue import enqueue

logger = logging.getLogger("qaclan.discovery_service")

_col_repo = CollectionRepo()
_req_repo = RequestRepo()
_folder_repo = FolderRepo()
_vars_repo = CollectionVarsRepo()


def _resolve_folders(project_id: str, collection_id: str, requests: list[dict]) -> dict[tuple, str]:
    """Ensure api_folders rows exist for every folder_path seen; return
    {tuple(path): folder_id}, top-down, memoized so repeated paths reuse
    the same folder instead of duplicating."""
    cache: dict[tuple, str] = {}
    for req in requests:
        path: tuple[str, ...] = tuple(req.get("folder_path") or [])
        if not path or path in cache:
            continue
        parent_id = None
        built: tuple[str, ...] = ()
        for name in path:
            built = built + (name,)
            if built in cache:
                parent_id = cache[built]
                continue
            if parent_id is None:
                folder = _folder_repo.get_or_create_root(project_id, collection_id, name)
            else:
                folder = _folder_repo.create(project_id, collection_id, name, parent_folder_id=parent_id)
            cache[built] = folder["id"]
            parent_id = folder["id"]
    return cache


def _apply_collection_extras(project_id: str, collection_id: str, collection_vars: dict | None,
                              collection_auth: tuple[str, dict] | None) -> None:
    for key, v in (collection_vars or {}).items():
        if isinstance(v, dict):
            value = str(v.get("value", ""))
            is_secret = bool(v.get("is_secret"))
        else:
            value = str(v)
            is_secret = False
        _vars_repo.upsert(collection_id, key, value, is_secret=is_secret)
    if collection_auth:
        auth_type, auth_config = collection_auth
        existing = _col_repo.get(collection_id, project_id) or {}
        _col_repo.update(
            collection_id,
            name=existing.get("name", "Imported Collection"),
            description=existing.get("description"),
            env_name=existing.get("env_name"),
            auth_type=auth_type,
            auth_config=json.dumps(auth_config),
        )

# Embedded (as literal source, not imported) in the generated recording
# harnesses below. Chromium only fills in Request.post_data_buffer from CDP's
# postDataEntries, and postDataEntries is only populated on requestWillBeSent
# when Fetch-domain interception is armed — with no route() handler
# registered it's always None for multipart bodies (verified empirically;
# JSON/urlencoded bodies don't need it, Chromium fills those via the plain
# postData text field regardless of interception). So a no-op route handler
# must be installed purely to arm interception before postData is readable.
_ROUTE_ARM_SRC = (
    "async def _arm_interception(ctx, pending_body_tasks):\n"
    "    async def _route_handler(route):\n"
    "        try:\n"
    "            req = route.request\n"
    # Measured against a real app: a post-login redirect can fire ~40ms
    # after the response — faster than an eager response.body() read can
    # complete (Python asyncio -> Node driver -> CDP round trip). Racing
    # the navigation loses even when the read starts immediately, so hold
    # navigation requests briefly until pending body reads finish instead —
    # see _RESPONSE_BODY_CAPTURE_SRC for why the read exists at all.
    "            if req.is_navigation_request():\n"
    "                for _ in range(16):\n"
    "                    if all(t.done() for t in pending_body_tasks):\n"
    "                        break\n"
    "                    await asyncio.sleep(0.05)\n"
    "            await route.continue_()\n"
    "        except Exception:\n"
    "            pass\n"
    "    await ctx.route('**/*', _route_handler)\n"
)

# Embedded (as literal source) alongside the blocks above. Playwright's own
# record_har loses response bodies for requests whose page navigates away
# shortly after the response arrives — Chromium destroys the resource
# before Playwright's (apparently deferred/batched) HAR body fetch runs,
# surfacing upstream as "No resource with given identifier found"
# (https://github.com/microsoft/playwright/issues/7348). A post-login
# redirect is the textbook trigger: the HAR entry ends up with no
# content.text at all. There is no upstream fix, so this reads each
# xhr/fetch response body itself, eagerly, in the same tick as the
# 'response' event — well before HAR finalization — and stashes it in a
# sidecar keyed by (method, url) for merge_response_bodies() to backfill
# into the HAR afterward. Must be flushed (awaited) before ctx.close():
# once the context closes, any body() call still in flight dies with it.
_RESPONSE_BODY_CAPTURE_SRC = (
    "def _install_response_body_capture(ctx):\n"
    "    captured = []\n"
    "    tasks = []\n"
    "    def on_response(resp):\n"
    "        req = resp.request\n"
    "        if req.resource_type not in ('xhr', 'fetch'):\n"
    "            return\n"
    "        async def _grab():\n"
    "            try:\n"
    # resp.body() has no built-in timeout — some responses (analytics
    # beacons, keepalive requests) never signal completion, and an
    # unbounded await here would hang the flush below, which runs before
    # ctx.close() and would eat into the harness's outer kill-timeout.
    "                body = await asyncio.wait_for(resp.body(), timeout=3)\n"
    "            except Exception:\n"
    "                return\n"
    "            captured.append({\n"
    "                'method': req.method,\n"
    "                'url': req.url,\n"
    "                'mimeType': (resp.headers.get('content-type', '') or '').split(';')[0].strip(),\n"
    "                'body_b64': base64.b64encode(body).decode('ascii'),\n"
    "            })\n"
    "        tasks.append(asyncio.ensure_future(_grab()))\n"
    "    ctx.on('response', on_response)\n"
    "    return captured, tasks\n"
    "\n"
    "async def _flush_response_body_capture(captured, tasks):\n"
    "    if tasks:\n"
    "        try:\n"
    "            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=4)\n"
    "        except asyncio.TimeoutError:\n"
    "            pass\n"
    "    if not captured:\n"
    "        return\n"
    "    try:\n"
    "        with open(os.environ['QACLAN_HAR_PATH'] + '.bodies.json', 'w') as sf:\n"
    "            json.dump(captured, sf)\n"
    "    except Exception:\n"
    "        pass\n"
)

# Embedded (as literal source, not imported) in the generated recording
# harnesses below. Playwright's own HAR export never captures postData for
# multipart/form-data bodies — Chrome's Network.requestWillBeSent omits it.
# A raw CDP Network.getRequestPostData call can fetch it, but that command
# hands the body back as a JSON string — Chromium encodes it UTF-8 before
# Python ever sees it, which corrupts binary file uploads (images, PDFs,
# etc.) since arbitrary bytes aren't valid UTF-8. Request.post_data_buffer
# gives the same body as raw bytes with no such round trip, so this listens
# on the page's native 'request' event and reads that instead. Results are
# stashed in a sidecar file next to the HAR, merged back in by
# cli.api_discovery.har_parser.merge_multipart_postdata. Requires
# _arm_interception (above) to have run first, or post_data_buffer is always
# None for multipart — see its docstring.
_MULTIPART_CAPTURE_SRC = (
    "def _install_multipart_capture(ctx):\n"
    "    captured = []\n"
    "    def on_request(req):\n"
    "        ct = req.headers.get('content-type', '') or ''\n"
    "        if 'multipart/form-data' not in ct.lower():\n"
    "            return\n"
    "        buf = req.post_data_buffer\n"
    "        if not buf:\n"
    "            return\n"
    "        captured.append({\n"
    "            'url': req.url,\n"
    "            'method': req.method,\n"
    "            'mimeType': ct,\n"
    "            'postData_b64': base64.b64encode(buf).decode('ascii'),\n"
    "        })\n"
    "    ctx.on('request', on_request)\n"
    "    return captured\n"
    "\n"
    "def _write_multipart_sidecar(captured):\n"
    "    if not captured:\n"
    "        return\n"
    "    try:\n"
    "        with open(os.environ['QACLAN_HAR_PATH'] + '.multipart.json', 'w') as sf:\n"
    "            json.dump(captured, sf)\n"
    "    except Exception:\n"
    "        pass\n"
)


def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    from web.api.services.doc_service import sync_doc_entry

    folder_cache = _resolve_folders(project_id, collection_id, requests) if collection_id else {}

    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)  # not a DB column
        folder_path = tuple(data.pop("folder_path", None) or [])
        if collection_id:
            data["collection_id"] = collection_id
            if folder_path:
                data["folder_id"] = folder_cache.get(folder_path)
        # Ensure JSON fields are lists/dicts (RequestRepo.create handles serialization)
        for key in ("headers", "params"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except (ValueError, TypeError):
                    data[key] = []
        if isinstance(data.get("assertions"), str):
            try:
                data["assertions"] = json.loads(data["assertions"])
            except (ValueError, TypeError):
                data["assertions"] = []
        if isinstance(data.get("auth_config"), str):
            try:
                data["auth_config"] = json.loads(data["auth_config"])
            except (ValueError, TypeError):
                data["auth_config"] = {}

        saved_req = _req_repo.create(project_id, data)
        enqueue("api_request", saved_req["id"], "upsert")

        # Sync to API docs if flagged (default: include)
        try:
            sync_doc_entry(project_id, {**data, 'id': saved_req['id']})
        except Exception as e:
            logger.warning("sync_doc_entry failed for %s: %s", data.get('url'), e)

        saved += 1
    return saved


def group_requests(requests: list[dict]) -> list[dict]:
    """Preview grouping for Save-as-Library. Pure computation — nothing persisted."""
    from cli.api_discovery.variant_grouper import group_requests as _group
    return _group(requests)


def save_library(project_id: str, groups: list[dict], collection_name: str, include_in_docs: int = 1) -> dict:
    """Persist the user's resolved per-group choices from the Save-as-Library
    comparison UI. See docs/superpowers/specs/2026-07-05-api-variant-library-design.md
    Sections 2, 4, 5.

    groups: [{action: "separate"|"merge", checked_fields: [field_key, ...],
              variants: [{request: {...}, included: bool, name_override: str|None}, ...]}]
    """
    from cli.api_discovery.schema_merger import merge_schemas
    from cli.api_discovery.variant_grouper import compute_diff_fields, suggest_label, templatize_request
    from web.api.repositories.request_example_repo import RequestExampleRepo
    from web.api.services.doc_service import sync_doc_entry

    col = _col_repo.create(project_id, collection_name)
    enqueue("api_collection", col["id"], "upsert")
    example_repo = RequestExampleRepo()
    saved = 0

    for group in groups:
        included = [v for v in group.get("variants", []) if v.get("included", True)]
        if not included:
            continue

        if group.get("action") == "merge" and len(included) > 1:
            checked_keys = set(group.get("checked_fields", []))
            default_req = dict(included[0]["request"])
            merged_req = templatize_request(default_req, checked_keys)
            merged_req["collection_id"] = col["id"]
            merged_req["include_in_docs"] = include_in_docs
            for k in ("response_status", "response_headers", "response_body", "duration_ms"):
                merged_req.pop(k, None)

            req_schema = None
            resp_schema = None
            for v in included:
                req_schema = merge_schemas(req_schema, v["request"].get("request_schema"))
                resp_schema = merge_schemas(resp_schema, v["request"].get("response_schema"))
            merged_req["request_schema"] = req_schema
            merged_req["response_schema"] = resp_schema

            saved_req = _req_repo.create(project_id, merged_req)
            enqueue("api_request", saved_req["id"], "upsert")
            try:
                sync_doc_entry(project_id, {**merged_req, "id": saved_req["id"]})
            except Exception as e:
                logger.warning("sync_doc_entry failed for merged request %s: %s", saved_req["id"], e)

            included_requests = [v["request"] for v in included]
            diff_fields = compute_diff_fields(included_requests)
            for i, v in enumerate(included[1:], start=1):
                r = v["request"]
                example = example_repo.create(saved_req["id"], {
                    "label": suggest_label(r, diff_fields, i),
                    "params": r.get("params", []),
                    "body": r.get("body") or r.get("body_form") or r.get("body_multipart") or r.get("body_graphql"),
                    "response_status": r.get("response_status"),
                    "response_headers": r.get("response_headers"),
                    "response_body": r.get("response_body"),
                })
                enqueue("api_request_example", example["id"], "upsert")
            saved += 1
        else:
            reqs = []
            for v in included:
                r = dict(v["request"])
                if v.get("name_override"):
                    r["name"] = v["name_override"]
                r["include_in_docs"] = include_in_docs
                reqs.append(r)
            saved += _save_requests(project_id, reqs, collection_id=col["id"])

    return {"imported": saved, "collection_id": col["id"]}


class DiscoveryService:
    def import_har(self, project_id: str, har_json: dict,
                   collection_name: str | None = None) -> dict:
        from cli.api_discovery.har_parser import parse_har
        requests = parse_har(har_json)
        col_id = None
        if collection_name and requests:
            col = _col_repo.create(project_id, collection_name)
            col_id = col["id"]
        count = _save_requests(project_id, requests, collection_id=col_id)
        logger.info("import_har: saved %d requests (collection_id=%s)", count, col_id)
        return {"imported": count, "collection_id": col_id}

    def import_openapi(self, project_id: str, spec_or_url, collection_name: str | None = None) -> dict:
        from cli.api_discovery.openapi_parser import parse_openapi
        if isinstance(spec_or_url, str) and spec_or_url.startswith("http"):
            import httpx
            resp = httpx.get(spec_or_url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                spec = resp.json()
            else:
                import yaml
                spec = yaml.safe_load(resp.text)
        else:
            spec = spec_or_url

        requests = parse_openapi(spec)

        if collection_name:
            col = _col_repo.create(project_id, collection_name)
            count = _save_requests(project_id, requests, collection_id=col["id"])
            logger.info("import_openapi: saved %d requests to collection '%s'", count, collection_name)
            return {"imported": count, "collections": [{"id": col["id"], "name": collection_name, "count": count}]}

        # Group by collection_name (tag)
        by_tag: dict[str, list] = {}
        for req in requests:
            tag = req.get("collection_name", "default")
            by_tag.setdefault(tag, []).append(req)

        collections_created = []
        total = 0
        for tag, tag_requests in by_tag.items():
            col = _col_repo.create(project_id, tag)
            count = _save_requests(project_id, tag_requests, collection_id=col["id"])
            total += count
            collections_created.append({"id": col["id"], "name": tag, "count": count})

        logger.info("import_openapi: saved %d requests across %d collections", total, len(collections_created))
        return {"imported": total, "collections": collections_created}

    def import_postman(self, project_id: str, collection_json: dict, collection_name: str | None = None) -> dict:
        from cli.api_discovery.postman_parser import parse_postman
        parsed = parse_postman(collection_json)
        requests = parsed["requests"]
        name = collection_name or collection_json.get("info", {}).get("name", "Imported Collection")

        col = _col_repo.create(project_id, name)
        total = _save_requests(project_id, requests, collection_id=col["id"])
        _apply_collection_extras(project_id, col["id"], parsed.get("collection_vars"), parsed.get("collection_auth"))

        logger.info("import_postman: saved %d requests to collection '%s', %d warnings",
                    total, name, len(parsed["warnings"]))
        return {"imported": total, "collection_id": col["id"], "warnings": parsed["warnings"]}

    def import_bruno(self, project_id: str, bru_files: list[dict], collection_name: str | None = None) -> dict:
        """bru_files: list of {name: str, content: str}. `name` may include
        `/`-separated folder path components (e.g. 'Auth/Login.bru'), and
        a file named 'collection.bru' or 'folder.bru' anywhere in the list
        is treated as collection-level settings (vars/auth), not a request."""
        from cli.api_discovery.bruno_parser import parse_bruno, parse_bruno_collection_settings
        col = _col_repo.create(project_id, collection_name or "Imported Collection")
        col_id = col["id"]

        all_warnings: list[str] = []
        total = 0
        for f in bru_files:
            rel_name = f.get("name", "Request.bru")
            base = rel_name.rsplit("/", 1)[-1]
            if base in ("collection.bru", "folder.bru"):
                settings = parse_bruno_collection_settings(f.get("content", ""))
                _apply_collection_extras(project_id, col_id, settings.get("vars"), settings.get("auth"))
                continue

            parsed = parse_bruno(f.get("content", ""))
            all_warnings.extend(parsed["warnings"])
            folder_path = rel_name.split("/")[:-1]
            for req in parsed["requests"]:
                if req.get("name") in ("Imported Request", "", None):
                    req["name"] = base.replace(".bru", "")
                req["folder_path"] = folder_path
            total += _save_requests(project_id, parsed["requests"], collection_id=col_id)

        logger.info("import_bruno: saved %d requests from %d files, %d warnings",
                    total, len(bru_files), len(all_warnings))
        return {"imported": total, "collection_id": col_id, "warnings": all_warnings}

    # ------------------------------------------------------------------ recording
    def launch_recorder(self, url: str, har_path: str, resolution: str | None = None):
        """Non-blocking. Launch Playwright browser to record HAR.
        Returns (proc, stop_file_path). On Windows, write any content to stop_file
        to trigger graceful shutdown (ctx.close() flushes HAR before process exits).
        On Unix, send SIGTERM to proc instead."""
        import os, tempfile, uuid
        stop_file = os.path.join(tempfile.gettempdir(), f"qaclan_stop_{uuid.uuid4().hex}.flag")
        harness = (
            "import asyncio, base64, json, os, signal, sys, traceback\n"
            "from playwright.async_api import async_playwright\n"
            f"{_MULTIPART_CAPTURE_SRC}\n"
            f"{_ROUTE_ARM_SRC}\n"
            f"{_RESPONSE_BODY_CAPTURE_SRC}\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx_opts = {'record_har_path': os.environ['QACLAN_HAR_PATH']}\n"
            "        viewport_env = os.environ.get('QACLAN_VIEWPORT', '')\n"
            "        if viewport_env:\n"
            "            try:\n"
            "                vw, vh = viewport_env.split('x')\n"
            "                ctx_opts['viewport'] = {'width': int(vw), 'height': int(vh)}\n"
            "            except ValueError:\n"
            "                pass\n"
            "        ctx = await browser.new_context(**ctx_opts)\n"
            "        page = await ctx.new_page()\n"
            "        captured = _install_multipart_capture(ctx)\n"
            "        body_captured, body_tasks = _install_response_body_capture(ctx)\n"
            "        await _arm_interception(ctx, body_tasks)\n"
            # Register signal handlers BEFORE goto() so SIGTERM during navigation is caught
            "        if sys.platform != 'win32':\n"
            "            stop = asyncio.Event()\n"
            "            loop = asyncio.get_running_loop()\n"
            "            loop.add_signal_handler(signal.SIGTERM, stop.set)\n"
            "            loop.add_signal_handler(signal.SIGINT, stop.set)\n"
            "            browser.on('disconnected', lambda _: stop.set())\n"
            "        try:\n"
            "            await page.goto(os.environ['QACLAN_START_URL'])\n"
            "        except Exception:\n"
            "            traceback.print_exc()\n"
            "        if sys.platform != 'win32':\n"
            "            await stop.wait()\n"
            "        else:\n"
            "            sf = os.environ.get('QACLAN_STOP_FILE', '')\n"
            "            while browser.is_connected() and not (sf and os.path.exists(sf)):\n"
            "                await asyncio.sleep(0.3)\n"
            # Flush pending response.body() reads BEFORE ctx.close() — once the
            # context is closed any in-flight body() call dies with it.
            "        await _flush_response_body_capture(body_captured, body_tasks)\n"
            "        try:\n"
            "            await ctx.close()\n"
            "        except Exception:\n"
            "            pass\n"
            "        _write_multipart_sidecar(captured)\n"
            "try:\n"
            "    asyncio.run(main())\n"
            "except Exception:\n"
            "    traceback.print_exc()\n"
            "    sys.exit(1)\n"
        )
        result = self._spawn_harness(url, har_path, harness, blocking=False, stop_file=stop_file, resolution=resolution)
        assert result is not None
        proc, harness_dir = result
        return proc, stop_file, harness_dir

    def record_sync(self, url: str, har_path: str) -> None:
        """Blocking. Returns when user closes browser. HAR flushed via ctx.close()."""
        harness = (
            "import asyncio, base64, json, os, traceback\n"
            "from playwright.async_api import async_playwright\n"
            f"{_MULTIPART_CAPTURE_SRC}\n"
            f"{_ROUTE_ARM_SRC}\n"
            f"{_RESPONSE_BODY_CAPTURE_SRC}\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            "        page = await ctx.new_page()\n"
            "        captured = _install_multipart_capture(ctx)\n"
            "        body_captured, body_tasks = _install_response_body_capture(ctx)\n"
            "        await _arm_interception(ctx, body_tasks)\n"
            "        try:\n"
            "            await page.goto(os.environ['QACLAN_START_URL'])\n"
            "        except Exception:\n"
            "            traceback.print_exc()\n"
            "        await browser.wait_for_event('disconnected')\n"
            "        await _flush_response_body_capture(body_captured, body_tasks)\n"
            "        await ctx.close()\n"
            "        _write_multipart_sidecar(captured)\n"
            "asyncio.run(main())\n"
        )
        self._spawn_harness(url, har_path, harness, blocking=True)

    def _spawn_harness(self, url: str, har_path: str, harness_src: str, blocking: bool, stop_file: str = "", resolution: str | None = None):
        import os, subprocess, sys, tempfile
        from cli import runtime_setup
        d = tempfile.mkdtemp(prefix="qaclan_record_")
        f = os.path.join(d, "record.py")
        with open(f, "w") as fh:
            fh.write(harness_src)
        venv_py = runtime_setup.venv_python()
        env = dict(os.environ)
        env["QACLAN_HAR_PATH"] = har_path
        env["QACLAN_START_URL"] = url
        if resolution:
            env["QACLAN_VIEWPORT"] = resolution
        if stop_file:
            env["QACLAN_STOP_FILE"] = stop_file
        bp = runtime_setup.browsers_path_if_present()
        if bp:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(bp)
        cmd = [str(venv_py) if venv_py.exists() else sys.executable, f]
        if blocking:
            import shutil
            try:
                result = subprocess.run(cmd, cwd=d, env=env)
                if result.returncode != 0:
                    logger.warning("record_sync harness exited non-zero: %d", result.returncode)
            finally:
                shutil.rmtree(d, ignore_errors=True)
        else:
            log_path = os.path.join(d, "record.log")
            try:
                with open(log_path, "w") as lf:
                    proc = subprocess.Popen(cmd, cwd=d, env=env, stdout=lf, stderr=lf)
            except Exception:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
                raise
            logger.info("record harness launched pid=%d log=%s", proc.pid, log_path)
            return proc, d
