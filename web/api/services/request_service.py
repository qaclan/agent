from __future__ import annotations
import logging
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.request_service")
_repo = RequestRepo()


def _validate_folder(project_id: str, folder_id: str, collection_id: str | None) -> None:
    from web.api.repositories.folder_repo import FolderRepo
    folder = FolderRepo().get(folder_id, project_id)
    if folder is None or folder["collection_id"] != collection_id:
        raise ValueError("Target folder not found in this collection")


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
        if data.get("folder_id"):
            _validate_folder(project_id, data["folder_id"], data.get("collection_id"))
        return _repo.create(project_id, data)

    def update(self, id: str, project_id: str, data: dict) -> dict:
        existing = _repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Request {id} not found")
        if data.get("folder_id"):
            collection_id = data.get("collection_id", existing.get("collection_id"))
            _validate_folder(project_id, data["folder_id"], collection_id)
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

    def list_examples(self, request_id: str, project_id: str) -> list[dict]:
        existing = _repo.get(request_id, project_id)
        if existing is None:
            raise LookupError(f"Request {request_id} not found")
        from web.api.repositories.request_example_repo import RequestExampleRepo
        return RequestExampleRepo().list_for_request(request_id)
