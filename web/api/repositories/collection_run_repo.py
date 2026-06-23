from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.collection_run_repo")


def _deser_result(row: dict) -> dict:
    out = dict(row)
    for key in ("response_headers", "assertion_results"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = None
    return out


class CollectionRunRepo:

    def create_run(self, collection_id: str, project_id: str, collection_name: str,
                   env_name: str | None, started_at: str) -> str:
        conn = get_conn()
        run_id = generate_id("arun")
        conn.execute(
            "INSERT INTO api_collection_runs "
            "(id, project_id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at) "
            "VALUES (?, ?, ?, ?, ?, 'RUNNING', 0, 0, 0, 0, ?)",
            (run_id, project_id, collection_id, collection_name, env_name, started_at),
        )
        conn.commit()
        logger.info("CollectionRunRepo.create_run: %s", run_id)
        return run_id

    def finish_run(self, run_id: str, status: str, total: int, passed: int,
                   failed: int, error_count: int, finished_at: str) -> None:
        conn = get_conn()
        conn.execute(
            "UPDATE api_collection_runs "
            "SET status=?, total=?, passed=?, failed=?, error_count=?, finished_at=? "
            "WHERE id=?",
            (status, total, passed, failed, error_count, finished_at, run_id),
        )
        conn.commit()
        logger.info("CollectionRunRepo.finish_run: %s → %s", run_id, status)

    def create_request_result(self, collection_run_id: str, req: dict,
                               result: dict, order_index: int) -> None:
        conn = get_conn()
        rid = generate_id("arreq")
        resp_headers = result.get("response_headers")
        assert_results = result.get("assertion_results")
        conn.execute(
            "INSERT INTO api_request_results "
            "(id, collection_run_id, api_request_id, request_name, method, url, order_index, "
            "status, status_code, response_body, response_headers, duration_ms, "
            "assertion_results, error_message, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid, collection_run_id, req["id"], req.get("name", ""), req.get("method"),
                result.get("url") or req.get("url", ""),
                order_index,
                result.get("status"), result.get("status_code"),
                result.get("response_body"),
                json.dumps(resp_headers) if resp_headers is not None else None,
                result.get("duration_ms"),
                json.dumps(assert_results) if assert_results is not None else None,
                result.get("error_message"),
                result.get("started_at"),
                result.get("finished_at"),
            ),
        )
        conn.commit()

    def list_runs(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at, finished_at "
            "FROM api_collection_runs WHERE project_id = ? "
            "ORDER BY started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at, finished_at "
            "FROM api_collection_runs WHERE id = ? AND project_id = ?",
            (run_id, project_id),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        result_rows = conn.execute(
            "SELECT id, api_request_id, request_name, method, url, order_index, "
            "status, status_code, response_body, response_headers, duration_ms, "
            "assertion_results, error_message, started_at, finished_at "
            "FROM api_request_results WHERE collection_run_id = ? ORDER BY order_index",
            (run_id,),
        ).fetchall()
        run["request_results"] = [_deser_result(dict(r)) for r in result_rows]
        return run
