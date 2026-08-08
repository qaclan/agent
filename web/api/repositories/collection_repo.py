from __future__ import annotations
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.collection_repo")


class CollectionRepo:
    def list(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT ac.id, ac.name, ac.description, ac.env_name, ac.auth_type, ac.auth_config, "
            "ac.schema_check_default, ac.negative_check_default, ac.order_index, ac.created_at, "
            "COUNT(ar.id) AS request_count "
            "FROM api_collections ac "
            "LEFT JOIN api_requests ar ON ar.collection_id = ac.id "
            "WHERE ac.project_id = ? "
            "GROUP BY ac.id ORDER BY ac.order_index, ac.created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT id, name, description, env_name, auth_type, auth_config, schema_check_default, negative_check_default, created_at FROM api_collections "
            "WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return dict(row) if row else None

    def create(self, project_id: str, name: str, description: str | None = None,
               env_name: str | None = None, auth_type: str = "none", auth_config: str = "{}") -> dict:
        conn = get_conn()
        cid = generate_id("apicol")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO api_collections (id, project_id, name, description, env_name, auth_type, auth_config, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, project_id, name, description, env_name, auth_type, auth_config, now),
        )
        conn.commit()
        logger.info("CollectionRepo.create: %s (%s)", name, cid)
        return {"id": cid, "name": name, "description": description, "env_name": env_name,
                "auth_type": auth_type, "auth_config": auth_config, "schema_check_default": "off",
                "negative_check_default": "off",
                "created_at": now, "request_count": 0}

    def set_schema_check_default(self, id: str, value: str) -> bool:
        """Set the collection-wide schema-check default ('on' | 'off').

        Dedicated setter so toggling the default never disturbs name/auth edits.
        Requests with an 'inherit' override follow this value at run time.
        """
        value = "on" if value == "on" else "off"
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET schema_check_default = ? WHERE id = ?",
            (value, id),
        )
        conn.commit()
        return cur.rowcount > 0

    def reset_schema_check_overrides(self, id: str) -> list[str]:
        """Reset every request's schema-check override in this collection to
        'inherit' so they all follow the collection default — the "global
        overwrites all" behavior. Returns the ids of requests actually changed
        (for sync re-push)."""
        conn = get_conn()
        rows = conn.execute(
            "SELECT id FROM api_requests WHERE collection_id = ? AND schema_check IS NOT NULL AND schema_check != 'inherit'",
            (id,),
        ).fetchall()
        changed = [r["id"] for r in rows]
        if changed:
            conn.execute(
                "UPDATE api_requests SET schema_check = 'inherit' WHERE collection_id = ?",
                (id,),
            )
            conn.commit()
        return changed

    def set_negative_check_default(self, id: str, value: str) -> bool:
        """Set the collection-wide negative-testing default ('on' | 'off').

        Requests with an 'inherit' override follow this value at run time."""
        value = "on" if value == "on" else "off"
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET negative_check_default = ? WHERE id = ?",
            (value, id),
        )
        conn.commit()
        return cur.rowcount > 0

    def reset_negative_check_overrides(self, id: str) -> list[str]:
        """Reset every request's negative-testing override in this collection to
        'inherit' so they all follow the collection default — the master-switch
        behavior. Returns the ids of requests actually changed (for sync re-push)."""
        conn = get_conn()
        rows = conn.execute(
            "SELECT id FROM api_requests WHERE collection_id = ? AND negative_check IS NOT NULL AND negative_check != 'inherit'",
            (id,),
        ).fetchall()
        changed = [r["id"] for r in rows]
        if changed:
            conn.execute(
                "UPDATE api_requests SET negative_check = 'inherit' WHERE collection_id = ?",
                (id,),
            )
            conn.commit()
        return changed

    def update(self, id: str, name: str, description: str | None = None,
               env_name: str | None = None, auth_type: str = "none", auth_config: str = "{}") -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET name = ?, description = ?, env_name = ?, auth_type = ?, auth_config = ? WHERE id = ?",
            (name, description, env_name, auth_type, auth_config, id),
        )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_collections WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0

    def set_order(self, id: str, project_id: str, order_index: int) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET order_index = ? WHERE id = ? AND project_id = ?",
            (order_index, id, project_id),
        )
        conn.commit()
        return cur.rowcount > 0
