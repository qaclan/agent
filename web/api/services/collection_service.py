from __future__ import annotations
import logging
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.collection_service")
_col_repo = CollectionRepo()
_req_repo = RequestRepo()


class CollectionService:
    def list(self, project_id: str) -> list[dict]:
        return _col_repo.list(project_id)

    def get(self, id: str, project_id: str) -> dict:
        col = _col_repo.get(id, project_id)
        if col is None:
            raise LookupError(f"Collection {id} not found")
        col["requests"] = _req_repo.list(project_id, collection_id=id)
        return col

    def create(self, project_id: str, name: str, description: str | None = None) -> dict:
        if not name or not name.strip():
            raise ValueError("Collection name is required")
        return _col_repo.create(project_id, name.strip(), description)

    def update(self, id: str, project_id: str, name: str, description: str | None = None) -> dict:
        if not name or not name.strip():
            raise ValueError("Collection name is required")
        existing = _col_repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Collection {id} not found")
        _col_repo.update(id, name.strip(), description)
        return _col_repo.get(id, project_id)

    def delete(self, id: str, project_id: str) -> bool:
        existing = _col_repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Collection {id} not found")
        return _col_repo.delete(id)
