from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.request_repo")

_DEFAULTS = {
    "method": "GET",
    "url": "",
    "headers": "[]",
    "params": "[]",
    "path_params": "[]",
    "body_type": None,
    "body": None,
    "auth_type": "inherit",
    "auth_config": "{}",
    "pre_script": None,
    "pre_lang": "js",
    "pre_extractor": "[]",
    "post_script": None,
    "post_lang": "js",
    "post_extractor": "[]",
    "request_schema": None,
    "response_schema": None,
    "assertions": "[]",
    "follow_redirects": 1,
    "timeout_ms": 30000,
}


def _serialize(data: dict) -> dict:
    """Ensure JSON list/dict fields are stored as TEXT."""
    out = dict(data)
    for key in ("headers", "params", "path_params", "assertions", "pre_extractor", "post_extractor"):
        if key in out and not isinstance(out[key], str):
            out[key] = json.dumps(out[key])
    for key in ("auth_config", "request_schema", "response_schema"):
        if key in out and out[key] is not None and not isinstance(out[key], str):
            out[key] = json.dumps(out[key])
    return out


def _deserialize(row: dict) -> dict:
    out = dict(row)
    for key in ("headers", "params", "path_params", "assertions", "pre_extractor", "post_extractor"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = []
    for key in ("auth_config", "request_schema", "response_schema"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = None if key != "auth_config" else {}
    return out


class RequestRepo:
    def list(self, project_id: str, collection_id: str | None = None) -> list[dict]:
        conn = get_conn()
        if collection_id:
            rows = conn.execute(
                "SELECT * FROM api_requests WHERE project_id = ? AND collection_id = ? ORDER BY created_at",
                (project_id, collection_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM api_requests WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [_deserialize(dict(r)) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_requests WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return _deserialize(dict(row)) if row else None

    def create(self, project_id: str, data: dict) -> dict:
        conn = get_conn()
        rid = generate_id("apireq")
        now = datetime.now(timezone.utc).isoformat()
        merged = {**_DEFAULTS, **_serialize(data)}
        conn.execute(
            "INSERT INTO api_requests (id, project_id, feature_id, collection_id, name, method, url, "
            "headers, params, path_params, body_type, body, auth_type, auth_config, pre_script, pre_lang, pre_extractor, "
            "post_script, post_lang, post_extractor, request_schema, response_schema, "
            "assertions, follow_redirects, timeout_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, project_id,
             merged.get("feature_id"), merged.get("collection_id"),
             merged.get("name", "Unnamed"), merged["method"], merged["url"],
             merged["headers"], merged["params"], merged["path_params"],
             merged["body_type"], merged["body"],
             merged["auth_type"], merged["auth_config"],
             merged["pre_script"], merged["pre_lang"], merged["pre_extractor"],
             merged["post_script"], merged["post_lang"], merged["post_extractor"],
             merged.get("request_schema"), merged.get("response_schema"),
             merged["assertions"], merged["follow_redirects"], merged["timeout_ms"],
             now),
        )
        conn.commit()
        logger.info("RequestRepo.create: %s (%s)", merged.get("name"), rid)
        return self.get(rid, project_id)

    def update(self, id: str, data: dict) -> bool:
        conn = get_conn()
        s = _serialize(data)
        fields = ["name", "method", "url", "headers", "params", "path_params", "body_type", "body",
                  "auth_type", "auth_config", "pre_script", "pre_lang", "pre_extractor", "post_script",
                  "post_lang", "post_extractor", "request_schema", "response_schema",
                  "assertions", "follow_redirects", "timeout_ms",
                  "feature_id", "collection_id"]
        updates = {f: s[f] for f in fields if f in s}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [id]
        cur = conn.execute(f"UPDATE api_requests SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_requests WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0
