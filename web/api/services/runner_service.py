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

        passed = sum(1 for r in results if r["status"] == "PASSED")
        failed = sum(1 for r in results if r["status"] == "FAILED")
        error_count = sum(1 for r in results if r["status"] == "ERROR")
        final_status = "PASSED" if (failed + error_count) == 0 else "FAILED"
        finished_at = datetime.now(timezone.utc).isoformat()

        run_repo.finish_run(
            run_id=run_id,
            status=final_status,
            total=len(requests),
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
            "total": len(requests),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
