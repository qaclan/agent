from __future__ import annotations
import logging
from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.folder_service")
_folder_repo = FolderRepo()
_col_repo = CollectionRepo()
_req_repo = RequestRepo()


class FolderService:
    def tree(self, collection_id: str, project_id: str) -> dict:
        if _col_repo.get(collection_id, project_id) is None:
            raise LookupError(f"Collection {collection_id} not found")
        return {
            "folders": _folder_repo.list_for_collection(collection_id),
            "requests": _req_repo.list(project_id, collection_id=collection_id),
        }

    def create(self, project_id: str, collection_id: str, name: str,
               parent_folder_id: str | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("Folder name is required")
        if _col_repo.get(collection_id, project_id) is None:
            raise LookupError(f"Collection {collection_id} not found")
        if parent_folder_id:
            self._validate_parent(collection_id, project_id, parent_folder_id)
        return _folder_repo.create(project_id, collection_id, name, parent_folder_id)

    def update(self, id: str, project_id: str, data: dict) -> dict:
        folder = _folder_repo.get(id, project_id)
        if folder is None:
            raise LookupError(f"Folder {id} not found")

        updates = {}
        if "name" in data:
            name = (data["name"] or "").strip()
            if not name:
                raise ValueError("Folder name is required")
            updates["name"] = name

        if "parent_folder_id" in data:
            parent_folder_id = data["parent_folder_id"]
            if parent_folder_id:
                if parent_folder_id == id:
                    raise ValueError("A folder cannot be its own parent")
                self._validate_parent(folder["collection_id"], project_id, parent_folder_id)
                self._assert_not_descendant(id, project_id, parent_folder_id)
            updates["parent_folder_id"] = parent_folder_id

        if updates:
            _folder_repo.update(id, updates)
        return _folder_repo.get(id, project_id)

    def delete(self, id: str, project_id: str) -> bool:
        if _folder_repo.get(id, project_id) is None:
            raise LookupError(f"Folder {id} not found")
        return _folder_repo.delete(id)

    def reorder(self, collection_id: str, project_id: str,
                parent_folder_id: str | None, items: list[dict]) -> None:
        if _col_repo.get(collection_id, project_id) is None:
            raise LookupError(f"Collection {collection_id} not found")
        if parent_folder_id:
            self._validate_parent(collection_id, project_id, parent_folder_id)
        for idx, item in enumerate(items):
            item_type, item_id = item.get("type"), item.get("id")
            if item_type == "folder":
                _folder_repo.set_order(item_id, collection_id, parent_folder_id, idx)
            elif item_type == "request":
                _req_repo.set_order(item_id, collection_id, parent_folder_id, idx)
            else:
                raise ValueError(f"Invalid item type: {item_type}")

    def _validate_parent(self, collection_id: str, project_id: str, parent_folder_id: str) -> None:
        parent = _folder_repo.get(parent_folder_id, project_id)
        if parent is None or parent["collection_id"] != collection_id:
            raise ValueError("Parent folder not found in this collection")

    def _assert_not_descendant(self, folder_id: str, project_id: str, target_parent_id: str) -> None:
        """Walk target_parent_id's ancestor chain; reject if folder_id appears in it —
        that would move a folder into its own descendant and create a cycle."""
        cursor_id = target_parent_id
        seen = set()
        while cursor_id:
            if cursor_id == folder_id:
                raise ValueError("Cannot move a folder into its own descendant")
            if cursor_id in seen:
                break  # defensive: already-corrupt chain, stop rather than loop forever
            seen.add(cursor_id)
            cursor = _folder_repo.get(cursor_id, project_id)
            cursor_id = cursor.get("parent_folder_id") if cursor else None
