from __future__ import annotations
import logging
from cli.db import get_conn
from cli.crypto import decrypt

logger = logging.getLogger("qaclan.env_loader")


def load_env_vars(project_id: str, env_name: str | None) -> dict:
    """Load and decrypt env vars for a named environment. Returns {} if env_name is None."""
    if not env_name:
        return {}
    conn = get_conn()
    env_row = conn.execute(
        "SELECT id FROM environments WHERE project_id = ? AND name = ?",
        (project_id, env_name),
    ).fetchone()
    if not env_row:
        raise LookupError(f"Environment '{env_name}' not found")
    rows = conn.execute(
        "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
        (env_row["id"],),
    ).fetchall()
    result = {}
    for v in rows:
        val = v["value"]
        if v["is_secret"] and val:
            try:
                val = decrypt(val)
            except Exception:
                pass
        result[v["key"]] = val
    logger.debug("load_env_vars: loaded %d vars for env '%s'", len(result), env_name)
    return result
