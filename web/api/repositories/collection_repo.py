from __future__ import annotations
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.collection_repo")


class CollectionRepo:
    def list(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT ac.id, ac.name, ac.description, ac.created_at, "
            "COUNT(ar.id) AS request_count "
            "FROM api_collections ac "
            "LEFT JOIN api_requests ar ON ar.collection_id = ac.id "
            "WHERE ac.project_id = ? "
            "GROUP BY ac.id ORDER BY ac.created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT id, name, description, created_at FROM api_collections "
            "WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return dict(row) if row else None

    def create(self, project_id: str, name: str, description: str | None = None) -> dict:
        conn = get_conn()
        cid = generate_id("apicol")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO api_collections (id, project_id, name, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, project_id, name, description, now),
        )
        conn.commit()
        logger.info("CollectionRepo.create: %s (%s)", name, cid)
        return {"id": cid, "name": name, "description": description, "created_at": now, "request_count": 0}

    def update(self, id: str, name: str, description: str | None = None) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET name = ?, description = ? WHERE id = ?",
            (name, description, id),
        )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_collections WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0
