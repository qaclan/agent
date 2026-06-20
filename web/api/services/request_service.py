from __future__ import annotations
import logging
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.request_service")
_repo = RequestRepo()


class RequestService:
    def list(self, project_id: str, collection_id: str | None = None) -> list[dict]:
        return _repo.list(project_id, collection_id=collection_id)

    def get(self, id: str, project_id: str) -> dict:
        req = _repo.get(id, project_id)
        if req is None:
            raise LookupError(f"Request {id} not found")
        return req

    def create(self, project_id: str, data: dict) -> dict:
        if not data.get("name", "").strip():
            raise ValueError("Request name is required")
        if not data.get("url", "").strip():
            raise ValueError("URL is required")
        return _repo.create(project_id, data)

    def update(self, id: str, project_id: str, data: dict) -> dict:
        existing = _repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Request {id} not found")
        _repo.update(id, data)
        return _repo.get(id, project_id)

    def delete(self, id: str, project_id: str) -> bool:
        existing = _repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Request {id} not found")
        return _repo.delete(id)

    def send(self, id: str, project_id: str, env_name: str | None = None) -> dict:
        """Run a single request ad-hoc (not stored in api_runs). Returns result dict."""
        from web.api.services.runner_service import RunnerService
        return RunnerService().run_request(id, project_id, env_name=env_name)
