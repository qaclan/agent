from __future__ import annotations

from datetime import datetime, timezone

from cli.db import generate_id, get_conn
from cli.crypto import encrypt, decrypt, is_encrypted


class CollectionVarsRepo:

    def list(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, key, initial_value, is_secret, created_at, runtime_value, runtime_env_name "
            "FROM collection_vars WHERE collection_id = ? ORDER BY key",
            (collection_id,),
        ).fetchall()
        return [
            {
                "id": r[0], "key": r[1], "initial_value": r[2], "is_secret": r[3], "created_at": r[4],
                "runtime_value": r[5], "runtime_env_name": r[6],
            }
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

    def upsert_runtime(self, collection_id: str, key: str, value: str,
                        env_name: str | None = None) -> dict:
        """Persist a script's qc.set output as the variable's runtime override,
        tagged with the environment bound to the collection when it was
        captured. Never touches initial_value — the user-authored static
        default. Creates the row (with an empty static default) if the key
        doesn't exist yet."""
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT id, is_secret FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()

        is_secret = bool(existing["is_secret"]) if existing else False
        raw = value or ""
        stored_value = encrypt(raw) if (is_secret and raw and not is_encrypted(raw)) else raw
        env_key = env_name or ""

        if existing:
            conn.execute(
                "UPDATE collection_vars SET runtime_value = ?, runtime_env_name = ? "
                "WHERE collection_id = ? AND key = ?",
                (stored_value, env_key, collection_id, key),
            )
            conn.commit()
            return {"id": existing["id"], "key": key, "runtime_value": stored_value, "runtime_env_name": env_key}

        vid = generate_id("cv")
        conn.execute(
            "INSERT INTO collection_vars "
            "(id, collection_id, key, initial_value, is_secret, runtime_value, runtime_env_name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, collection_id, key, "", 0, stored_value, env_key, now),
        )
        conn.commit()
        return {"id": vid, "key": key, "runtime_value": stored_value, "runtime_env_name": env_key, "created_at": now}

    def delete(self, collection_id: str, key: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def as_seed_dict(self, collection_id: str, env_name: str | None = None) -> dict[str, str]:
        """Return {key: value} for seeding state before a run, decrypting secrets.

        A variable's runtime override (a prior qc.set capture) is used only if
        it was captured under the same environment currently bound to the
        collection (`env_name`); otherwise the static initial_value default is
        used. This keeps a script-captured value from outliving an environment
        switch or an unset environment.
        """
        result: dict[str, str] = {}
        active_env = env_name or ""
        for v in self.list(collection_id):
            runtime_value = v.get("runtime_value")
            runtime_env = v.get("runtime_env_name")
            if runtime_value is not None and (runtime_env or "") == active_env:
                val = runtime_value
            else:
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
