"""Converts harness-captured requests (script-run capture, see
docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) into the
exact shape cli.api_discovery.har_parser.parse_har() produces — reusing its
sensitive-value redaction, browser-header skip-list, query-param splitting,
and request/response schema inference instead of duplicating any of it.
"""

from __future__ import annotations

from urllib.parse import urlsplit, parse_qsl

from cli.api_discovery.har_parser import parse_har


def _content_type(headers: dict | None) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == "content-type":
            return v
    return ""


def _to_har_entry(captured: dict) -> dict:
    url = captured.get("url", "")
    query = urlsplit(url).query
    query_string = [
        {"name": k, "value": v}
        for k, v in parse_qsl(query, keep_blank_values=True)
    ]
    req_headers = captured.get("request_headers") or {}
    resp_headers = captured.get("response_headers") or {}

    post_data = {}
    if captured.get("request_body"):
        post_data = {
            "mimeType": _content_type(req_headers),
            "text": captured["request_body"],
        }

    return {
        # Marks this as an XHR/fetch entry so parse_har()'s _should_skip()
        # never filters it out — the harness already filtered at capture time.
        "_resourceType": "fetch",
        "time": captured.get("duration_ms") or 0,
        "request": {
            "method": captured.get("method", "GET"),
            "url": url,
            "headers": [{"name": k, "value": v} for k, v in req_headers.items()],
            "queryString": query_string,
            "postData": post_data,
        },
        "response": {
            "status": captured.get("status_code"),
            "headers": [{"name": k, "value": v} for k, v in resp_headers.items()],
            "content": {
                "mimeType": _content_type(resp_headers),
                "text": captured.get("response_body") or "",
            },
        },
    }


def parse_captured_requests(captured: list[dict]) -> list[dict]:
    """Redact + shape-convert raw harness capture entries by routing them
    through parse_har() — the same redaction/parsing HAR import and Record
    APIs mode already use, so results are indistinguishable from those paths
    to every downstream consumer (request-review-modal.js, save-requests,
    group-requests, save-library)."""
    if not captured:
        return []
    entries = [_to_har_entry(c) for c in captured]
    return parse_har({"log": {"entries": entries}})
