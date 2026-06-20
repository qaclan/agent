from __future__ import annotations
import json
import logging
from cli.db import get_conn
from cli.config import get_active_project_id
from cli.env_loader import load_env_vars

logger = logging.getLogger("qaclan.runner_service")


class RunnerService:
    def run_request(self, request_id: str, project_id: str, env_name: str | None = None) -> dict:
        """Run a single api_request ad-hoc. Result is NOT stored in api_runs."""
        from web.api.repositories.request_repo import RequestRepo
        from cli.api_runner import run_api_request

        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")

        env_vars = load_env_vars(project_id, env_name)
        state: dict = {}

        result = run_api_request(req, env_vars, state, state_path=None)
        return result

    def run_collection(self, collection_id: str, project_id: str,
                       env_name: str | None = None) -> dict:
        """Run all requests in a collection sequentially. Results returned in-memory, NOT stored in api_runs."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from cli.api_runner import run_api_request

        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        env_vars = load_env_vars(project_id, env_name)

        state: dict = {}
        results = []
        passed = failed = 0

        for idx, req in enumerate(requests):
            result = run_api_request(req, env_vars, state, state_path=None)
            results.append({
                "request_id": req["id"],
                "name": req["name"],
                "method": req["method"],
                "url": req["url"],
                **result,
            })
            if result["status"] == "PASSED":
                passed += 1
            else:
                failed += 1

        final_status = "PASSED" if failed == 0 else "FAILED"
        return {
            "collection_id": collection_id,
            "collection_name": col["name"],
            "status": final_status,
            "total": len(requests),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
