from __future__ import annotations

from datetime import datetime, timezone

from cli.db import generate_id, get_conn


class CollectionVarsRepo:

    def list(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, key, initial_value, created_at FROM collection_vars "
            "WHERE collection_id = ? ORDER BY key",
            (collection_id,),
        ).fetchall()
        return [{"id": r[0], "key": r[1], "initial_value": r[2], "created_at": r[3]} for r in rows]

    def upsert(self, collection_id: str, key: str, initial_value: str) -> dict:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT id FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE collection_vars SET initial_value = ? WHERE collection_id = ? AND key = ?",
                (initial_value, collection_id, key),
            )
            conn.commit()
            return {"id": existing[0], "key": key, "initial_value": initial_value}
        vid = generate_id("cv")
        conn.execute(
            "INSERT INTO collection_vars (id, collection_id, key, initial_value, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (vid, collection_id, key, initial_value, now),
        )
        conn.commit()
        return {"id": vid, "key": key, "initial_value": initial_value, "created_at": now}

    def delete(self, collection_id: str, key: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def as_seed_dict(self, collection_id: str) -> dict[str, str]:
        """Return {key: initial_value} for seeding state before a run."""
        return {v["key"]: v["initial_value"] for v in self.list(collection_id)}
