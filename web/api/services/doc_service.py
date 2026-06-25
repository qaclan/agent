from __future__ import annotations
import logging

logger = logging.getLogger("qaclan.doc_service")


def sync_doc_entry(project_id: str, req: dict) -> None:
    """Upsert an api_doc_entries row from a saved api_request dict.

    Merges schemas with any existing doc entry for the same (method, path_pattern).
    No-op if include_in_docs is falsy.
    """
    if not req.get('include_in_docs', 1):
        return

    from cli.api_discovery.url_normalizer import normalize_url
    from cli.api_discovery.schema_merger import merge_schemas
    from web.api.repositories.doc_repo import DocRepo

    method = req.get('method', 'GET').upper()
    url = req.get('url', '')
    if not url:
        return

    path_pattern = normalize_url(url)
    repo = DocRepo()

    # Get existing entry to merge schemas
    existing_entries = [
        e for e in repo.list(project_id)
        if e['method'] == method and e['path_pattern'] == path_pattern
    ]
    existing = existing_entries[0] if existing_entries else None

    # Merge schemas
    new_req_schema = req.get('request_schema')
    new_resp_schema = req.get('response_schema')

    merged_req_schema = merge_schemas(
        existing.get('request_schema') if existing else None,
        new_req_schema,
    )
    merged_resp_schema = merge_schemas(
        existing.get('response_schema') if existing else None,
        new_resp_schema,
    )

    # Build headers schema (merge common request header keys)
    headers = req.get('headers', [])
    if isinstance(headers, str):
        import json
        try:
            headers = json.loads(headers)
        except Exception:
            headers = []
    headers_schema = {h['key']: 'string' for h in headers if h.get('key')}
    merged_headers = merge_schemas(
        existing.get('headers_schema') if existing else None,
        headers_schema or None,
    )

    # Build params schema
    params = req.get('params', [])
    if isinstance(params, str):
        import json
        try:
            params = json.loads(params)
        except Exception:
            params = []
    params_schema = {p['key']: 'string' for p in params if p.get('key')}
    merged_params = merge_schemas(
        existing.get('params_schema') if existing else None,
        params_schema or None,
    )

    # Track source request IDs
    source_ids = list(existing.get('source_request_ids', []) if existing else [])
    req_id = req.get('id')
    if req_id and req_id not in source_ids:
        source_ids.append(req_id)

    repo.upsert(project_id, method, path_pattern, {
        'request_schema': merged_req_schema,
        'response_schema': merged_resp_schema,
        'headers_schema': merged_headers,
        'params_schema': merged_params,
        'source_request_ids': source_ids,
    })
    logger.info("sync_doc_entry: %s %s → %s", method, url, path_pattern)
