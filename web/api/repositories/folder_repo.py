from __future__ import annotations
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.folder_repo")


class FolderRepo:
    def list_for_collection(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM api_folders WHERE collection_id = ? ORDER BY order_index, created_at",
            (collection_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_folders WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return dict(row) if row else None

    def create(self, project_id: str, collection_id: str, name: str,
               parent_folder_id: str | None = None) -> dict:
        conn = get_conn()
        fid = generate_id("apifold")
        now = datetime.now(timezone.utc).isoformat()
        if parent_folder_id:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) FROM api_folders "
                "WHERE collection_id = ? AND parent_folder_id = ?",
                (collection_id, parent_folder_id),
            ).fetchone()[0]
        else:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) FROM api_folders "
                "WHERE collection_id = ? AND parent_folder_id IS NULL",
                (collection_id,),
            ).fetchone()[0]
        conn.execute(
            "INSERT INTO api_folders (id, project_id, collection_id, parent_folder_id, name, order_index, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fid, project_id, collection_id, parent_folder_id, name, max_order + 1, now),
        )
        conn.commit()
        logger.info("FolderRepo.create: %s (%s)", name, fid)
        return self.get(fid, project_id)

    def get_or_create_root(self, project_id: str, collection_id: str, name: str) -> dict:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_folders WHERE collection_id = ? AND parent_folder_id IS NULL AND name = ?",
            (collection_id, name),
        ).fetchone()
        if row:
            return dict(row)
        return self.create(project_id, collection_id, name)

    def update(self, id: str, data: dict) -> bool:
        conn = get_conn()
        fields = ["name", "parent_folder_id"]
        updates = {f: data[f] for f in fields if f in data}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [id]
        cur = conn.execute(f"UPDATE api_folders SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cur.rowcount > 0

    def set_order(self, id: str, collection_id: str, parent_folder_id: str | None, order_index: int) -> bool:
        conn = get_conn()
        if parent_folder_id:
            cur = conn.execute(
                "UPDATE api_folders SET order_index = ? WHERE id = ? AND collection_id = ? AND parent_folder_id = ?",
                (order_index, id, collection_id, parent_folder_id),
            )
        else:
            cur = conn.execute(
                "UPDATE api_folders SET order_index = ? WHERE id = ? AND collection_id = ? AND parent_folder_id IS NULL",
                (order_index, id, collection_id),
            )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_folders WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0
