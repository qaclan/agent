from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.doc_repo")

_JSON_COLS = ('request_schema', 'response_schema', 'headers_schema', 'params_schema', 'source_request_ids')


def _serialize(data: dict) -> dict:
    out = dict(data)
    for key in _JSON_COLS:
        if key in out and out[key] is not None and not isinstance(out[key], str):
            out[key] = json.dumps(out[key])
    return out


def _deserialize(row: dict) -> dict:
    out = dict(row)
    for key in _JSON_COLS:
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = [] if key == 'source_request_ids' else None
    return out


class DocRepo:
    def upsert(self, project_id: str, method: str, path_pattern: str, data: dict) -> dict:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        method = method.upper()

        existing = conn.execute(
            "SELECT * FROM api_doc_entries WHERE project_id = ? AND method = ? AND path_pattern = ?",
            (project_id, method, path_pattern),
        ).fetchone()

        s = _serialize(data)

        if existing:
            row_id = existing['id']
            updates = {
                k: s.get(k)
                for k in ('request_schema', 'response_schema', 'headers_schema',
                          'params_schema', 'description', 'source_request_ids')
                if k in s
            }
            updates['last_seen_at'] = now
            set_clause = ', '.join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE api_doc_entries SET {set_clause} WHERE id = ?",
                list(updates.values()) + [row_id],
            )
            conn.commit()
            return self.get(project_id, row_id)

        row_id = generate_id('apidoc')
        conn.execute(
            "INSERT INTO api_doc_entries "
            "(id, project_id, method, path_pattern, description, "
            "request_schema, response_schema, headers_schema, params_schema, "
            "source_request_ids, include_in_docs, first_seen_at, last_seen_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row_id, project_id, method, path_pattern,
                s.get('description'),
                s.get('request_schema'), s.get('response_schema'),
                s.get('headers_schema'), s.get('params_schema'),
                s.get('source_request_ids', '[]'),
                1, now, now,
            ),
        )
        conn.commit()
        logger.info("DocRepo.upsert: %s %s (%s)", method, path_pattern, row_id)
        return self.get(project_id, row_id)

    def list(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM api_doc_entries WHERE project_id = ? ORDER BY path_pattern, method",
            (project_id,),
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]

    def get(self, project_id: str, entry_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_doc_entries WHERE id = ? AND project_id = ?",
            (entry_id, project_id),
        ).fetchone()
        return _deserialize(dict(row)) if row else None

    def delete(self, project_id: str, entry_id: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM api_doc_entries WHERE id = ? AND project_id = ?",
            (entry_id, project_id),
        )
        conn.commit()
        return cur.rowcount > 0
