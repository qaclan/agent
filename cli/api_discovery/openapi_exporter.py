from __future__ import annotations
import re


def _schema_to_openapi(schema) -> dict:
    """Convert our type-string schema tree to OpenAPI JSON Schema format."""
    if schema is None or schema == '?':
        return {}
    if isinstance(schema, str):
        _type_map = {
            'string': 'string', 'number': 'number', 'boolean': 'boolean',
            'null': 'string', '...': 'string',
        }
        # Handle union types like "string|number" from merge
        if '|' in schema:
            types = [t.strip() for t in schema.split('|')]
            non_null = [t for t in types if t != 'null']
            t = _type_map.get(non_null[0], 'string') if non_null else 'string'
        else:
            t = _type_map.get(schema, 'string')
        return {'type': t}
    if isinstance(schema, list):
        item_schema = _schema_to_openapi(schema[0]) if schema else {}
        return {'type': 'array', 'items': item_schema}
    if isinstance(schema, dict):
        props = {k: _schema_to_openapi(v) for k, v in schema.items()}
        return {'type': 'object', 'properties': props}
    return {}


def export_openapi(doc_entries: list[dict], project_name: str = 'API') -> dict:
    """Generate an OpenAPI 3.0 spec dict from api_doc_entries rows."""
    paths: dict = {}

    for entry in doc_entries:
        if not entry.get('include_in_docs', 1):
            continue

        path = entry['path_pattern']
        method = entry['method'].lower()

        operation: dict = {
            'summary': f"{entry['method']} {path}",
            'operationId': re.sub(r'[^a-zA-Z0-9]', '_', f"{entry['method']}_{path}").strip('_'),
            'responses': {'200': {'description': 'Success'}},
        }

        # Path parameters
        path_params = re.findall(r'\{([^}]+)\}', path)
        if path_params:
            operation['parameters'] = [
                {'name': p, 'in': 'path', 'required': True, 'schema': {'type': 'string'}}
                for p in path_params
            ]

        # Query parameters from params_schema
        params_schema = entry.get('params_schema') or {}
        if isinstance(params_schema, dict) and params_schema:
            query_params = operation.setdefault('parameters', [])
            for k in params_schema:
                query_params.append({'name': k, 'in': 'query', 'required': False, 'schema': {'type': 'string'}})

        # Request body (POST/PUT/PATCH only)
        if method in ('post', 'put', 'patch') and entry.get('request_schema'):
            operation['requestBody'] = {
                'required': True,
                'content': {
                    'application/json': {
                        'schema': _schema_to_openapi(entry['request_schema'])
                    }
                }
            }

        # Response schema
        if entry.get('response_schema'):
            operation['responses']['200']['content'] = {
                'application/json': {
                    'schema': _schema_to_openapi(entry['response_schema'])
                }
            }

        if path not in paths:
            paths[path] = {}
        paths[path][method] = operation

    return {
        'openapi': '3.0.0',
        'info': {'title': project_name, 'version': '1.0.0'},
        'paths': paths,
    }


def export_openapi_yaml(doc_entries: list[dict], project_name: str = 'API') -> str:
    """Return OpenAPI 3.0 as a YAML string."""
    import yaml
    return yaml.dump(export_openapi(doc_entries, project_name), sort_keys=False, allow_unicode=True)
