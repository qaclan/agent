from __future__ import annotations

from datetime import datetime, timezone

from cli.db import generate_id, get_conn
from cli.crypto import encrypt, decrypt, is_encrypted


class CollectionVarsRepo:

    def list(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, key, initial_value, is_secret, created_at FROM collection_vars "
            "WHERE collection_id = ? ORDER BY key",
            (collection_id,),
        ).fetchall()
        return [
            {"id": r[0], "key": r[1], "initial_value": r[2], "is_secret": r[3], "created_at": r[4]}
            for r in rows
        ]

    def upsert(self, collection_id: str, key: str, initial_value: str,
               is_secret: bool = False, unchanged: bool = False) -> dict:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT id, initial_value FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()

        if unchanged and is_secret and existing:
            # UI signalled no edit — retain existing ciphertext
            value = existing["initial_value"]
        else:
            raw = initial_value or ""
            if is_secret and raw and not is_encrypted(raw):
                value = encrypt(raw)
            else:
                value = raw

        is_secret_int = int(bool(is_secret))

        if existing:
            conn.execute(
                "UPDATE collection_vars SET initial_value = ?, is_secret = ? "
                "WHERE collection_id = ? AND key = ?",
                (value, is_secret_int, collection_id, key),
            )
            conn.commit()
            return {"id": existing["id"], "key": key, "initial_value": value, "is_secret": is_secret_int}

        vid = generate_id("cv")
        conn.execute(
            "INSERT INTO collection_vars (id, collection_id, key, initial_value, is_secret, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (vid, collection_id, key, value, is_secret_int, now),
        )
        conn.commit()
        return {"id": vid, "key": key, "initial_value": value, "is_secret": is_secret_int, "created_at": now}

    def delete(self, collection_id: str, key: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def as_seed_dict(self, collection_id: str) -> dict[str, str]:
        """Return {key: initial_value} for seeding state before a run, decrypting secrets."""
        result: dict[str, str] = {}
        for v in self.list(collection_id):
            val = v["initial_value"]
            if v["is_secret"] and val:
                val = decrypt(val)
            result[v["key"]] = val
        return result

    def reveal(self, collection_id: str, key: str) -> str | None:
        """Return decrypted plaintext for a single var, or None if it doesn't exist."""
        conn = get_conn()
        row = conn.execute(
            "SELECT initial_value, is_secret FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()
        if not row:
            return None
        value = row["initial_value"] or ""
        if row["is_secret"] and value:
            value = decrypt(value)
        return value
