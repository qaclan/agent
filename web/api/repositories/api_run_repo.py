from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.api_run_repo")


def _deser(row: dict) -> dict:
    out = dict(row)
    for key in ("response_headers", "assertion_results"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = None
    return out


class ApiRunRepo:
    def create(self, suite_run_id: str, api_request_id: str, order_index: int, result: dict) -> dict:
        conn = get_conn()
        rid = generate_id("apirun")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO api_runs (id, suite_run_id, api_request_id, order_index, status, "
            "status_code, response_body, response_headers, duration_ms, assertion_results, "
            "error_message, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, suite_run_id, api_request_id, order_index,
             result.get("status"), result.get("status_code"),
             result.get("response_body"),
             json.dumps(result.get("response_headers")) if result.get("response_headers") is not None else None,
             result.get("duration_ms"),
             json.dumps(result.get("assertion_results")) if result.get("assertion_results") is not None else None,
             result.get("error_message"),
             result.get("started_at", now),
             result.get("finished_at", now)),
        )
        conn.commit()
        logger.info("ApiRunRepo.create: %s for suite_run %s", rid, suite_run_id)
        return self.get(rid)

    def list_by_suite_run(self, suite_run_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT ar.*, req.name AS request_name, req.method, req.url "
            "FROM api_runs ar "
            "JOIN api_requests req ON ar.api_request_id = req.id "
            "WHERE ar.suite_run_id = ? ORDER BY ar.order_index",
            (suite_run_id,),
        ).fetchall()
        return [_deser(dict(r)) for r in rows]

    def get(self, id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT ar.*, req.name AS request_name, req.method, req.url "
            "FROM api_runs ar "
            "JOIN api_requests req ON ar.api_request_id = req.id "
            "WHERE ar.id = ?",
            (id,),
        ).fetchone()
        return _deser(dict(row)) if row else None
