from __future__ import annotations
import json
import logging
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.discovery_service")

_col_repo = CollectionRepo()
_req_repo = RequestRepo()


def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    from web.api.services.doc_service import sync_doc_entry

    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)  # not a DB column
        if collection_id:
            data["collection_id"] = collection_id
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
            "import asyncio, os, signal, sys, traceback\n"
            "from playwright.async_api import async_playwright\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            # Register signal handlers BEFORE goto() so SIGTERM during navigation is caught
            "        if sys.platform != 'win32':\n"
            "            stop = asyncio.Event()\n"
            "            loop = asyncio.get_running_loop()\n"
            "            loop.add_signal_handler(signal.SIGTERM, stop.set)\n"
            "            loop.add_signal_handler(signal.SIGINT, stop.set)\n"
            "            browser.on('disconnected', lambda _: stop.set())\n"
            "        await (await ctx.new_page()).goto(os.environ['QACLAN_START_URL'])\n"
            "        if sys.platform != 'win32':\n"
            "            await stop.wait()\n"
            "        else:\n"
            "            sf = os.environ.get('QACLAN_STOP_FILE', '')\n"
            "            while browser.is_connected() and not (sf and os.path.exists(sf)):\n"
            "                await asyncio.sleep(0.3)\n"
            "        try:\n"
            "            await ctx.close()\n"
            "        except Exception:\n"
            "            pass\n"
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
            "import asyncio, os\n"
            "from playwright.async_api import async_playwright\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            "        await (await ctx.new_page()).goto(os.environ['QACLAN_START_URL'])\n"
            "        await browser.wait_for_event('disconnected')\n"
            "        await ctx.close()\n"
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
            with open(log_path, "w") as lf:
                proc = subprocess.Popen(cmd, cwd=d, env=env, stdout=lf, stderr=lf)
            logger.info("record harness launched pid=%d log=%s", proc.pid, log_path)
            return proc, d
