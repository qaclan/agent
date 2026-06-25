from __future__ import annotations
import json
import logging
from cli.db import get_conn
from cli.config import get_active_project_id
from cli.env_loader import load_env_vars

logger = logging.getLogger("qaclan.runner_service")


def _resolve_auth(req: dict, col: dict | None) -> dict:
    """Return req with auth resolved: 'inherit' replaced by collection's auth."""
    if req.get("auth_type") != "inherit" or col is None:
        return req
    resolved = dict(req)
    resolved["auth_type"] = col.get("auth_type") or "none"
    resolved["auth_config"] = col.get("auth_config") or "{}"
    return resolved


class RunnerService:
    def run_request(self, request_id: str, project_id: str, env_name: str | None = None) -> dict:
        """Run a single api_request ad-hoc. Result is NOT stored in api_runs."""
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.collection_vars_repo import CollectionVarsRepo
        from cli.api_runner import run_api_request

        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")

        col = None
        if req.get("collection_id"):
            col = CollectionRepo().get(req["collection_id"], project_id)

        # Inherit env from collection if not specified
        if not env_name and col:
            env_name = col.get("env_name")

        env_vars = load_env_vars(project_id, env_name)

        # Seed state with collection vars initial values
        seed_vars: dict = {}
        if req.get("collection_id"):
            seed_vars = CollectionVarsRepo().as_seed_dict(req["collection_id"])
        state: dict = {"qaclan_vars": seed_vars} if seed_vars else {}

        result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)

        # Persist extracted vars back to collection_vars so subsequent single sends see them
        if result.get("state_updates") and req.get("collection_id"):
            from web.api.repositories.collection_vars_repo import CollectionVarsRepo
            vars_repo = CollectionVarsRepo()
            for key, value in result["state_updates"].items():
                vars_repo.upsert(req["collection_id"], key, str(value))

        return result

    def start_collection_run(self, collection_id: str, project_id: str,
                              env_name: str | None = None,
                              seed_vars: dict | None = None) -> tuple[str, bool]:
        """
        Returns (run_id, already_running).
        If a RUNNING run exists for this collection, returns it without spawning a new thread.
        """
        import threading
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_run_repo import CollectionRunRepo
        from datetime import datetime, timezone

        run_repo = CollectionRunRepo()

        existing_run_id = run_repo.get_running_for_collection(collection_id)
        if existing_run_id:
            logger.info("start_collection_run: collection %s already running as %s", collection_id, existing_run_id)
            return existing_run_id, True

        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        started_at = datetime.now(timezone.utc).isoformat()
        run_id = run_repo.create_run(
            collection_id=collection_id,
            project_id=project_id,
            collection_name=col["name"],
            env_name=env_name,
            started_at=started_at,
            total=len(requests),
        )

        thread = threading.Thread(
            target=self._execute_collection,
            args=(run_id, collection_id, project_id, env_name, seed_vars),
            daemon=True,
        )
        thread.start()
        logger.info("start_collection_run: run_id=%s thread started", run_id)
        return run_id, False

    def _execute_collection(self, run_id: str, collection_id: str, project_id: str,
                             env_name: str | None, seed_vars: dict | None) -> None:
        """Thread target. Checks stop_requested before each request."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_run_repo import CollectionRunRepo
        from cli.api_runner import run_api_request
        from datetime import datetime, timezone

        run_repo = CollectionRunRepo()
        results: list = []
        final_status = "ERROR"

        try:
            col = CollectionRepo().get(collection_id, project_id)
            if col is None:
                logger.error("_execute_collection: collection %s not found", collection_id)
                return

            requests = RequestRepo().list(project_id, collection_id=collection_id)
            env_vars = load_env_vars(project_id, env_name)
            state: dict = {"qaclan_vars": dict(seed_vars)} if seed_vars else {}

            for idx, req in enumerate(requests):
                if run_repo.is_stop_requested(run_id):
                    logger.info("_execute_collection: stop requested at idx %d for run %s", idx, run_id)
                    final_status = "STOPPED"
                    break
                run_repo.update_current_index(run_id, idx)
                result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)
                results.append(result)
                run_repo.create_request_result(run_id, req, result, idx)
            else:
                passed = sum(1 for r in results if r.get("status") == "PASSED")
                failed_c = sum(1 for r in results if r.get("status") == "FAILED")
                err_c = sum(1 for r in results if r.get("status") == "ERROR")
                final_status = "PASSED" if (failed_c + err_c) == 0 and results else "FAILED"

        except Exception:
            logger.exception("_execute_collection: unhandled error in run %s", run_id)

        finally:
            passed = sum(1 for r in results if r.get("status") == "PASSED")
            failed_c = sum(1 for r in results if r.get("status") == "FAILED")
            err_c = sum(1 for r in results if r.get("status") == "ERROR")
            run_repo.finish_run(
                run_id=run_id,
                status=final_status,
                total=len(results),
                passed=passed,
                failed=failed_c,
                error_count=err_c,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.info("_execute_collection: run %s → %s", run_id, final_status)

    def run_collection(self, collection_id: str, project_id: str,
                       env_name: str | None = None,
                       seed_vars: dict | None = None) -> dict:
        """Run all requests in a collection sequentially. Results persisted to api_collection_runs."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from web.api.repositories.collection_run_repo import CollectionRunRepo
        from cli.api_runner import run_api_request
        from datetime import datetime, timezone

        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        env_vars = load_env_vars(project_id, env_name)

        state: dict = {"qaclan_vars": dict(seed_vars)} if seed_vars else {}

        started_at = datetime.now(timezone.utc).isoformat()
        run_repo = CollectionRunRepo()
        run_id = run_repo.create_run(
            collection_id=collection_id,
            project_id=project_id,
            collection_name=col["name"],
            env_name=env_name,
            started_at=started_at,
        )

        results = []
        try:
            for idx, req in enumerate(requests):
                result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)
                results.append({
                    "request_id": req["id"],
                    "name": req["name"],
                    "method": req["method"],
                    "url": result.get("url", ""),
                    **result,
                })
                run_repo.create_request_result(run_id, req, result, idx)
        finally:
            passed = sum(1 for r in results if r["status"] == "PASSED")
            failed = sum(1 for r in results if r["status"] == "FAILED")
            error_count = sum(1 for r in results if r["status"] == "ERROR")
            final_status = "PASSED" if (failed + error_count) == 0 else "FAILED"
            finished_at = datetime.now(timezone.utc).isoformat()
            run_repo.finish_run(
                run_id=run_id,
                status=final_status,
                total=len(results),
                passed=passed,
                failed=failed,
                error_count=error_count,
                finished_at=finished_at,
            )

        return {
            "run_id": run_id,
            "collection_id": collection_id,
            "collection_name": col["name"],
            "status": final_status,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
