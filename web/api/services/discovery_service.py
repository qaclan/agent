from __future__ import annotations
import json
import logging
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.discovery_service")

_col_repo = CollectionRepo()
_req_repo = RequestRepo()

# Embedded (as literal source, not imported) in the generated recording
# harnesses below. Playwright's own HAR export never captures postData for
# multipart/form-data bodies — Chrome's Network.requestWillBeSent omits it,
# and Playwright's HAR writer doesn't fall back to the CDP command that can
# actually fetch it (Network.getRequestPostData). This installs that fallback
# via a raw CDP session and stashes results in a sidecar file next to the HAR,
# merged back in by cli.api_discovery.har_parser.merge_multipart_postdata.
_MULTIPART_CDP_CAPTURE_SRC = (
    "async def _install_multipart_capture(ctx, page):\n"
    "    cdp = await ctx.new_cdp_session(page)\n"
    "    await cdp.send('Network.enable')\n"
    "    captured = []\n"
    "    def on_request(event):\n"
    "        req = event.get('request', {})\n"
    "        ct = ''\n"
    "        for k, v in (req.get('headers') or {}).items():\n"
    "            if k.lower() == 'content-type':\n"
    "                ct = v\n"
    "                break\n"
    "        if req.get('hasPostData') and 'multipart/form-data' in ct.lower():\n"
    "            request_id = event.get('requestId')\n"
    "            async def fetch_body():\n"
    "                try:\n"
    "                    res = await cdp.send('Network.getRequestPostData', {'requestId': request_id})\n"
    "                    captured.append({'url': req.get('url'), 'method': req.get('method'), 'postData': res.get('postData'), 'mimeType': ct})\n"
    "                except Exception:\n"
    "                    pass\n"
    "            asyncio.create_task(fetch_body())\n"
    "    cdp.on('Network.requestWillBeSent', on_request)\n"
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


def _resolve_folder_id(project_id: str, collection_id: str, url: str, folder_cache: dict) -> str | None:
    """Get-or-create a root-level folder named after url's first meaningful path
    segment, memoized in folder_cache for the duration of one save call so that
    many requests mapping to the same folder name share one folder instead of
    creating duplicates."""
    from cli.api_discovery.folder_suggester import suggest_folder_name
    from web.api.repositories.folder_repo import FolderRepo

    name = suggest_folder_name(url)
    if not name:
        return None
    if name in folder_cache:
        return folder_cache[name]
    folder = FolderRepo().get_or_create_root(project_id, collection_id, name)
    folder_cache[name] = folder["id"]
    return folder["id"]


def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None,
                    organize_into_folders: bool = False, folder_cache: dict | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    from web.api.services.doc_service import sync_doc_entry

    if folder_cache is None:
        folder_cache = {}
    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)  # not a DB column
        if collection_id:
            data["collection_id"] = collection_id
            if organize_into_folders:
                data["folder_id"] = _resolve_folder_id(project_id, collection_id, data.get("url", ""), folder_cache)
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


def save_library(project_id: str, groups: list[dict], collection_name: str, include_in_docs: int = 1,
                  organize_into_folders: bool = False) -> dict:
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
    example_repo = RequestExampleRepo()
    folder_cache: dict = {}
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
            if organize_into_folders:
                merged_req["folder_id"] = _resolve_folder_id(project_id, col["id"], merged_req.get("url", ""), folder_cache)
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
            try:
                sync_doc_entry(project_id, {**merged_req, "id": saved_req["id"]})
            except Exception as e:
                logger.warning("sync_doc_entry failed for merged request %s: %s", saved_req["id"], e)

            included_requests = [v["request"] for v in included]
            diff_fields = compute_diff_fields(included_requests)
            for i, v in enumerate(included[1:], start=1):
                r = v["request"]
                example_repo.create(saved_req["id"], {
                    "label": suggest_label(r, diff_fields, i),
                    "params": r.get("params", []),
                    "body": r.get("body"),
                    "response_status": r.get("response_status"),
                    "response_headers": r.get("response_headers"),
                    "response_body": r.get("response_body"),
                })
            saved += 1
        else:
            reqs = []
            for v in included:
                r = dict(v["request"])
                if v.get("name_override"):
                    r["name"] = v["name_override"]
                r["include_in_docs"] = include_in_docs
                reqs.append(r)
            saved += _save_requests(project_id, reqs, collection_id=col["id"],
                                     organize_into_folders=organize_into_folders, folder_cache=folder_cache)

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
        requests = parse_postman(collection_json)

        if collection_name:
            col = _col_repo.create(project_id, collection_name)
            total = _save_requests(project_id, requests, collection_id=col["id"])
            logger.info("import_postman: saved %d requests to collection '%s'", total, collection_name)
            return {"imported": total}

        # Group by collection_name (folder)
        by_folder: dict[str, list] = {}
        for req in requests:
            folder = req.get("collection_name", "Imported")
            by_folder.setdefault(folder, []).append(req)

        total = 0
        for folder, folder_reqs in by_folder.items():
            col = _col_repo.create(project_id, folder)
            total += _save_requests(project_id, folder_reqs, collection_id=col["id"])

        logger.info("import_postman: saved %d requests", total)
        return {"imported": total}

    def import_bruno(self, project_id: str, bru_files: list[dict], collection_name: str | None = None) -> dict:
        """bru_files: list of {name: str, content: str}"""
        from cli.api_discovery.bruno_parser import parse_bruno
        col_id = None
        if collection_name:
            col = _col_repo.create(project_id, collection_name)
            col_id = col["id"]
        total = 0
        for f in bru_files:
            requests = parse_bruno(f.get("content", ""))
            for req in requests:
                if req.get("name") in ("Imported Request", "", None):
                    req["name"] = f.get("name", "Request").replace(".bru", "")
            total += _save_requests(project_id, requests, collection_id=col_id)

        logger.info("import_bruno: saved %d requests from %d files", total, len(bru_files))
        return {"imported": total}

    # ------------------------------------------------------------------ recording
    def launch_recorder(self, url: str, har_path: str):
        """Non-blocking. Launch Playwright browser to record HAR.
        Returns (proc, stop_file_path). On Windows, write any content to stop_file
        to trigger graceful shutdown (ctx.close() flushes HAR before process exits).
        On Unix, send SIGTERM to proc instead."""
        import os, tempfile, uuid
        stop_file = os.path.join(tempfile.gettempdir(), f"qaclan_stop_{uuid.uuid4().hex}.flag")
        harness = (
            "import asyncio, json, os, signal, sys, traceback\n"
            "from playwright.async_api import async_playwright\n"
            f"{_MULTIPART_CDP_CAPTURE_SRC}\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            "        page = await ctx.new_page()\n"
            "        captured = await _install_multipart_capture(ctx, page)\n"
            # Register signal handlers BEFORE goto() so SIGTERM during navigation is caught
            "        if sys.platform != 'win32':\n"
            "            stop = asyncio.Event()\n"
            "            loop = asyncio.get_running_loop()\n"
            "            loop.add_signal_handler(signal.SIGTERM, stop.set)\n"
            "            loop.add_signal_handler(signal.SIGINT, stop.set)\n"
            "            browser.on('disconnected', lambda _: stop.set())\n"
            "        await page.goto(os.environ['QACLAN_START_URL'])\n"
            "        if sys.platform != 'win32':\n"
            "            await stop.wait()\n"
            "        else:\n"
            "            sf = os.environ.get('QACLAN_STOP_FILE', '')\n"
            "            while browser.is_connected() and not (sf and os.path.exists(sf)):\n"
            "                await asyncio.sleep(0.3)\n"
            "        await asyncio.sleep(0.2)\n"  # let in-flight getRequestPostData calls finish
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
        result = self._spawn_harness(url, har_path, harness, blocking=False, stop_file=stop_file)
        assert result is not None
        proc, harness_dir = result
        return proc, stop_file, harness_dir

    def record_sync(self, url: str, har_path: str) -> None:
        """Blocking. Returns when user closes browser. HAR flushed via ctx.close()."""
        harness = (
            "import asyncio, json, os\n"
            "from playwright.async_api import async_playwright\n"
            f"{_MULTIPART_CDP_CAPTURE_SRC}\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            "        page = await ctx.new_page()\n"
            "        captured = await _install_multipart_capture(ctx, page)\n"
            "        await page.goto(os.environ['QACLAN_START_URL'])\n"
            "        await browser.wait_for_event('disconnected')\n"
            "        await asyncio.sleep(0.2)\n"  # let in-flight getRequestPostData calls finish
            "        await ctx.close()\n"
            "        _write_multipart_sidecar(captured)\n"
            "asyncio.run(main())\n"
        )
        self._spawn_harness(url, har_path, harness, blocking=True)

    def _spawn_harness(self, url: str, har_path: str, harness_src: str, blocking: bool, stop_file: str = ""):
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
