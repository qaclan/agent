from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger("qaclan.openapi_parser")


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref string within the spec."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node.get(part, {})
    return node


def _schema_to_example(schema: dict, spec: dict, depth: int = 0) -> object:
    """Generate a sample value from a JSON Schema node."""
    if depth > 5:
        return None
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    stype = schema.get("type", "object")
    if stype == "object":
        props = schema.get("properties", {})
        return {k: _schema_to_example(v, spec, depth + 1) for k, v in props.items()}
    if stype == "array":
        items = schema.get("items", {})
        return [_schema_to_example(items, spec, depth + 1)]
    if stype == "string":
        return schema.get("enum", ["string"])[0]
    if stype == "integer":
        return 0
    if stype == "number":
        return 0.0
    if stype == "boolean":
        return True
    return None


def _parse_openapi3(spec: dict) -> list[dict]:
    results = []
    servers = spec.get("servers", [{}])
    base_url = servers[0].get("url", "") if servers else ""

    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            op = path_item.get(method)
            if not op:
                continue

            tags = op.get("tags", ["default"])
            collection_name = tags[0] if tags else "default"
            op_id = op.get("operationId", "")
            summary = op.get("summary", "")
            name = summary or op_id or f"{method.upper()} {path}"

            # Parameters → headers + query params
            headers = []
            params = []
            for param in op.get("parameters", []) + path_item.get("parameters", []):
                if "$ref" in param:
                    param = _resolve_ref(spec, param["$ref"])
                p_name = param.get("name", "")
                p_in = param.get("in", "query")
                example = _schema_to_example(param.get("schema", {}), spec)
                value = str(example) if example is not None else ""
                if p_in == "query":
                    params.append({"key": p_name, "value": value, "enabled": True})
                elif p_in == "header":
                    headers.append({"key": p_name, "value": value, "enabled": True})
                # path params — substitute in URL
                if p_in == "path":
                    path = path.replace("{" + p_name + "}", value or f"{{{p_name}}}")

            # Request body
            body_type = None
            body = None
            req_body = op.get("requestBody", {})
            if "$ref" in req_body:
                req_body = _resolve_ref(spec, req_body["$ref"])
            content = req_body.get("content", {})
            if "application/json" in content:
                schema = content["application/json"].get("schema", {})
                example = _schema_to_example(schema, spec)
                body_type = "raw"
                body = json.dumps(example, indent=2)
            elif "application/x-www-form-urlencoded" in content:
                body_type = "form"
                schema = content["application/x-www-form-urlencoded"].get("schema", {})
                example = _schema_to_example(schema, spec)
                form_items = []
                if isinstance(example, dict):
                    form_items = [{"key": k, "value": str(v), "enabled": True} for k, v in example.items()]
                body = json.dumps(form_items)

            # Generate status assertion from responses
            assertions = []
            for status_str in op.get("responses", {}):
                try:
                    code = int(status_str)
                    if 200 <= code < 300:
                        assertions.append({"type": "status", "op": "lt", "value": 400})
                        break
                except ValueError:
                    pass

            url = base_url.rstrip("/") + path

            results.append({
                "name": name,
                "method": method.upper(),
                "url": url,
                "headers": headers,
                "params": params,
                "body_type": body_type,
                "body": body,
                "auth_type": "none",
                "auth_config": "{}",
                "assertions": json.dumps(assertions),
                "collection_name": collection_name,
            })
    return results


def _parse_swagger2(spec: dict) -> list[dict]:
    results = []
    host = spec.get("host", "localhost")
    base_path = spec.get("basePath", "/")
    schemes = spec.get("schemes", ["https"])
    base_url = f"{schemes[0]}://{host}{base_path}".rstrip("/")

    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue

            tags = op.get("tags", ["default"])
            collection_name = tags[0] if tags else "default"
            name = op.get("summary") or op.get("operationId") or f"{method.upper()} {path}"

            params = []
            headers = []
            body_type = None
            body = None

            for param in op.get("parameters", []):
                if "$ref" in param:
                    param = _resolve_ref(spec, param["$ref"])
                p_name = param.get("name", "")
                p_in = param.get("in", "query")
                if p_in == "query":
                    params.append({"key": p_name, "value": "", "enabled": True})
                elif p_in == "header":
                    headers.append({"key": p_name, "value": "", "enabled": True})
                elif p_in == "body":
                    schema = param.get("schema", {})
                    example = _schema_to_example(schema, spec)
                    body_type = "raw"
                    body = json.dumps(example, indent=2)

            url = base_url + path
            results.append({
                "name": name,
                "method": method.upper(),
                "url": url,
                "headers": headers,
                "params": params,
                "body_type": body_type,
                "body": body,
                "auth_type": "none",
                "auth_config": "{}",
                "assertions": "[]",
                "collection_name": collection_name,
            })
    return results


def parse_openapi(spec: dict) -> list[dict]:
    """Parse OpenAPI 3.x or Swagger 2.x spec → list of request dicts."""
    if "openapi" in spec:
        return _parse_openapi3(spec)
    elif "swagger" in spec:
        return _parse_swagger2(spec)
    else:
        logger.warning("parse_openapi: unrecognised spec format")
        return []
