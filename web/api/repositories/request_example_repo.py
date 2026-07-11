from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.request_example_repo")


class RequestExampleRepo:
    def create(self, api_request_id: str, data: dict) -> dict:
        conn = get_conn()
        eid = generate_id("apiex")
        now = datetime.now(timezone.utc).isoformat()
        params = data.get("params", [])
        headers = data.get("response_headers")
        conn.execute(
            "INSERT INTO api_request_examples "
            "(id, api_request_id, label, params, body, response_status, response_headers, response_body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eid, api_request_id, data.get("label", "variant"),
                json.dumps(params) if not isinstance(params, str) else params,
                data.get("body"),
                data.get("response_status"),
                json.dumps(headers) if headers is not None and not isinstance(headers, str) else headers,
                data.get("response_body"),
                now,
            ),
        )
        conn.commit()
        logger.info("RequestExampleRepo.create: %s for request %s", data.get("label"), api_request_id)
        return self.get(eid)

    def get(self, id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute("SELECT * FROM api_request_examples WHERE id = ?", (id,)).fetchone()
        return self._deserialize(dict(row)) if row else None

    def list_for_request(self, api_request_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM api_request_examples WHERE api_request_id = ? ORDER BY created_at",
            (api_request_id,),
        ).fetchall()
        return [self._deserialize(dict(r)) for r in rows]

    @staticmethod
    def _deserialize(row: dict) -> dict:
        out = dict(row)
        for key in ("params", "response_headers"):
            if isinstance(out.get(key), str):
                try:
                    out[key] = json.loads(out[key])
                except (ValueError, TypeError):
                    out[key] = [] if key == "params" else {}
        return out
