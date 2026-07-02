from __future__ import annotations
import json
import logging
import os
import re
import subprocess
import tempfile
import base64
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("qaclan.api_runner")

_SENSITIVE_KEY_RE = re.compile(
    r"(password|secret|token|authorization|api.?key|auth)", re.IGNORECASE
)
_VAR_RE = re.compile(r"\{\{([^}]+)\}\}")
_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def _substitute_path_params(url: str, path_params: list, env_vars: dict, state: dict) -> str:
    """Replace {param} URL segments with values from path_params list.
    Values may contain {{VAR}} references — resolve those first.
    """
    if not path_params or not url:
        return url
    lookup = {
        item["key"]: resolve_vars(str(item.get("value", "")), env_vars, state)
        for item in path_params
        if item.get("enabled", True) and item.get("key", "").strip()
    }
    return _PATH_PARAM_RE.sub(lambda m: lookup.get(m.group(1), m.group(0)), url)


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

def resolve_vars(text: str, env_vars: dict, state: dict) -> str:
    """Replace {{var_name}} in text. Order: env_vars → state.qaclan_vars → empty+warn."""
    if not text:
        return text or ""
    qc_vars = state.get("qaclan_vars", {}) if isinstance(state, dict) else {}

    def _replace(m):
        key = m.group(1).strip()
        if key in env_vars:
            return str(env_vars[key])
        if key in qc_vars:
            return str(qc_vars[key])
        logger.warning("resolve_vars: variable '%s' not found in env or state", key)
        return ""

    return _VAR_RE.sub(_replace, text)


def _resolve_list(items: list, env_vars: dict, state: dict) -> list:
    """Resolve vars in a list of {key, value, enabled} dicts."""
    out = []
    for item in items:
        if not item.get("enabled", True):
            continue
        out.append({
            "key": resolve_vars(str(item.get("key", "")), env_vars, state),
            "value": resolve_vars(str(item.get("value", "")), env_vars, state),
        })
    return out


# ---------------------------------------------------------------------------
# Auth injection
# ---------------------------------------------------------------------------

def _apply_auth(headers: dict, params: dict, auth_type: str, auth_config: dict,
                env_vars: dict, state: dict) -> tuple[dict, dict]:
    """Return updated (headers, params) with auth applied."""
    headers = dict(headers)
    params = dict(params)

    def _set_auth(value: str) -> None:
        for k in list(headers.keys()):
            if k.lower() == "authorization":
                del headers[k]
        headers["Authorization"] = value

    if auth_type == "bearer":
        token = resolve_vars(auth_config.get("token", ""), env_vars, state)
        if token:
            _set_auth(f"Bearer {token}")

    elif auth_type == "basic":
        username = resolve_vars(auth_config.get("username", ""), env_vars, state)
        password = resolve_vars(auth_config.get("password", ""), env_vars, state)
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        _set_auth(f"Basic {encoded}")

    elif auth_type == "api_key":
        key_name = resolve_vars(auth_config.get("key", "X-API-Key"), env_vars, state)
        key_value = resolve_vars(auth_config.get("value", ""), env_vars, state)
        location = auth_config.get("in", "header")
        if location == "query":
            params[key_name] = key_value
        else:
            headers[key_name] = key_value

    elif auth_type == "oauth2":
        # Client credentials grant — POST to token_url, cache in state
        token_url = resolve_vars(auth_config.get("token_url", ""), env_vars, state)
        client_id = resolve_vars(auth_config.get("client_id", ""), env_vars, state)
        client_secret = resolve_vars(auth_config.get("client_secret", ""), env_vars, state)
        cache_key = f"__oauth2_token_{token_url}"
        qc_vars = state.setdefault("qaclan_vars", {})
        token = qc_vars.get(cache_key)
        if not token and token_url:
            try:
                import httpx
                resp = httpx.post(token_url, data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }, timeout=15)
                resp.raise_for_status()
                token = resp.json().get("access_token", "")
                qc_vars[cache_key] = token
            except Exception as e:
                logger.warning("OAuth2 token fetch failed: %s", e)
                token = ""
        if token:
            _set_auth(f"Bearer {token}")

    return headers, params


# ---------------------------------------------------------------------------
# Script sandbox
# ---------------------------------------------------------------------------

def _build_python_sandbox(script: str, context: dict) -> str:
    ctx_json = json.dumps(context)
    header = (
        "import json, os\n"
        "_ctx = " + ctx_json + "\n"
        '_output = {"headers": dict(_ctx.get("headers", {})), "params": dict(_ctx.get("params", {})), "state": {}}\n'
        "class _Qc:\n"
        "    def set(self, k, v): _output['state'][k] = v\n"
        "    def set_header(self, k, v): _output['headers'][k] = v\n"
        "    def set_param(self, k, v): _output['params'][k] = v\n"
        "qc = _Qc()\n"
        'response_body = _ctx.get("response_body", "")\n'
        'response_headers = _ctx.get("response_headers", {})\n'
        'status_code = _ctx.get("status_code", 0)\n'
        "class _Resp:\n"
        "    def json(s): return json.loads(response_body)\n"
        "    headers = response_headers\n"
        "response = _Resp()\n"
    )
    footer = (
        '\n_out = os.environ.get("QACLAN_SANDBOX_OUTPUT")\n'
        "if _out:\n"
        "    with open(_out, 'w') as _f: json.dump(_output, _f)\n"
    )
    return header + script + "\n" + footer


def _build_js_sandbox(script: str, context: dict) -> str:
    ctx_json = json.dumps(context)
    header = (
        "const _ctx = " + ctx_json + ";\n"
        "const _output = { headers: Object.assign({}, _ctx.headers), params: Object.assign({}, _ctx.params), state: {} };\n"
        "const qc = { set:(k,v)=>_output.state[k]=v, setHeader:(k,v)=>_output.headers[k]=v, setParam:(k,v)=>_output.params[k]=v };\n"
        "const response = { json:()=>JSON.parse(_ctx.response_body||'null'), headers:_ctx.response_headers||{}, status:_ctx.status_code||0 };\n"
    )
    footer = (
        "\nconst fs=require('fs'); const out=process.env.QACLAN_SANDBOX_OUTPUT;"
        " if(out) fs.writeFileSync(out,JSON.stringify(_output));\n"
    )
    return header + script + "\n" + footer


def _apply_extractor(rules: list, response_body: str, state: dict) -> dict:
    """Apply post_extractor rules to response JSON. Returns {name: value} of extracted vars."""
    if not rules:
        return {}
    try:
        data = json.loads(response_body)
    except (ValueError, TypeError):
        logger.warning("_apply_extractor: response is not JSON, skipping")
        return {}
    extracted = {}
    for rule in rules:
        path = rule.get("path", "").strip()
        name = rule.get("name", "").strip()
        if name.startswith("{{") and name.endswith("}}"):
            name = name[2:-2].strip()
        if not path or not name:
            continue
        value = data
        for key in path.split("."):
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list):
                try:
                    value = value[int(key)]
                except (ValueError, IndexError):
                    value = None
            else:
                value = None
            if value is None:
                break
        if value is None:
            logger.warning("_apply_extractor: path '%s' not found in response", path)
            continue
        prefix = rule.get("prefix", "")
        final = prefix + str(value)
        extracted[name] = final
        logger.info("_apply_extractor: %s = %.40s", name, final)
    return extracted


def _run_script_sandbox(script: str, lang: str, context: dict, state_path: str | None) -> dict:
    """Run pre/post script in subprocess sandbox. Returns {headers, params, state} or empty dict on error."""
    if not script or not script.strip():
        return {}

    from cli import runtime_setup

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = os.path.join(tmpdir, "output.json")
        env = os.environ.copy()
        env["QACLAN_SANDBOX_OUTPUT"] = output_file

        if lang == "python":
            wrapper = _build_python_sandbox(script, context)
            script_file = os.path.join(tmpdir, "sandbox.py")
            Path(script_file).write_text(wrapper, encoding="utf-8")
            venv_python = runtime_setup.venv_python()
            cmd = [str(venv_python) if venv_python else "python3", script_file]
        else:  # js (default)
            wrapper = _build_js_sandbox(script, context)
            script_file = os.path.join(tmpdir, "sandbox.js")
            Path(script_file).write_text(wrapper, encoding="utf-8")
            node = runtime_setup.node_bin("node")
            cmd = [str(node) if node else "node", script_file]

        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.warning("sandbox script failed (exit %d): %s", result.returncode, result.stderr[:500])
                return {}
            if os.path.exists(output_file):
                with open(output_file) as f:
                    return json.load(f)
            return {}
        except subprocess.TimeoutExpired:
            logger.warning("sandbox script timed out")
            return {}
        except Exception as e:
            logger.warning("sandbox script error: %s", e)
            return {}


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def _compare(actual, op: str, expected) -> bool:
    if op == "eq":
        return str(actual) == str(expected)
    if op == "ne":
        return str(actual) != str(expected)
    if op == "lt":
        return float(actual) < float(expected)
    if op == "gt":
        return float(actual) > float(expected)
    if op == "contains":
        return str(expected) in str(actual)
    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None
    if op == "matches":
        return bool(re.search(str(expected), str(actual)))
    return False


def _evaluate_assertions(assertions: list, status_code: int, response_body: str,
                          response_headers: dict, duration_ms: int) -> list[dict]:
    """Evaluate all assertions. Returns list of result dicts."""
    from jsonpath_ng import parse as jp_parse

    results = []
    try:
        body_json = json.loads(response_body) if response_body else None
    except (ValueError, TypeError):
        body_json = None

    for assertion in assertions:
        atype = assertion.get("type")
        op = assertion.get("op", "eq")
        expected = assertion.get("value")
        result = {"type": atype, "op": op, "value": expected, "passed": False, "actual": None}

        try:
            if atype == "status":
                actual = status_code
                result["actual"] = actual
                result["passed"] = _compare(actual, op, int(expected))

            elif atype == "json_path":
                path = assertion.get("path", "$")
                result["path"] = path
                if body_json is None:
                    result["passed"] = False
                    result["actual"] = None
                else:
                    expr = jp_parse(path)
                    matches = [m.value for m in expr.find(body_json)]
                    actual = matches[0] if matches else None
                    result["actual"] = actual
                    if op in ("exists", "not_exists"):
                        result["passed"] = _compare(actual if matches else None, op, expected)
                    else:
                        result["passed"] = _compare(actual, op, expected) if matches else False

            elif atype == "header":
                key = assertion.get("key", "")
                actual = response_headers.get(key) or response_headers.get(key.lower())
                result["key"] = key
                result["actual"] = actual
                result["passed"] = _compare(actual, op, expected)

            elif atype == "response_time":
                actual = duration_ms
                result["actual"] = actual
                result["passed"] = _compare(actual, op, int(expected))

            elif atype == "body_text":
                actual = response_body or ""
                result["actual"] = actual[:200]
                result["passed"] = _compare(actual, op, expected)

        except Exception as e:
            logger.warning("assertion eval error (%s): %s", atype, e)
            result["error"] = str(e)
            result["passed"] = False

        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_api_request(req: dict, env_vars: dict, state: dict, state_path: str | None = None) -> dict:
    """
    Execute a single API request.

    Args:
        req: api_request row dict (already deserialized JSON fields)
        env_vars: {key: value} from active environment
        state: parsed state.json dict (may contain qaclan_vars)
        state_path: path to state.json file (for sandbox scripts that write state)

    Returns:
        dict with keys: status, status_code, url, response_body, response_headers,
                        duration_ms, assertion_results, error_message, state_updates
    """
    import httpx

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()
    url = req.get("url", "")          # initialised before try so error returns always have a url

    try:
        # 1. Resolve variables in URL, headers, params
        url = resolve_vars(req.get("url", ""), env_vars, state)

        raw_path_params = req.get("path_params", [])
        if isinstance(raw_path_params, str):
            raw_path_params = json.loads(raw_path_params)
        if raw_path_params:
            url = _substitute_path_params(url, raw_path_params, env_vars, state)

        raw_headers = req.get("headers", [])
        if isinstance(raw_headers, str):
            raw_headers = json.loads(raw_headers)
        resolved_headers_list = _resolve_list(raw_headers, env_vars, state)
        headers = {item["key"]: item["value"] for item in resolved_headers_list if item["key"]}
        # Drop Authorization header if it resolved to a bare scheme with no token
        # (e.g. "Bearer " when {{access_token}} was missing) — httpx rejects these
        _auth_key = next((k for k in headers if k.lower() == "authorization"), None)
        if _auth_key:
            _parts = headers[_auth_key].strip().split(None, 1)
            if len(_parts) < 2 or not _parts[1].strip():
                del headers[_auth_key]

        raw_params = req.get("params", [])
        if isinstance(raw_params, str):
            raw_params = json.loads(raw_params)
        resolved_params_list = _resolve_list(raw_params, env_vars, state)
        params = {item["key"]: item["value"] for item in resolved_params_list if item["key"]}

        # 2. Apply auth
        auth_type = req.get("auth_type", "none")
        auth_config = req.get("auth_config", {})
        if isinstance(auth_config, str):
            auth_config = json.loads(auth_config)
        headers, params = _apply_auth(headers, params, auth_type, auth_config, env_vars, state)
        # 2.5. Pre-extractor — extract from previous request's response, before pre-script
        pre_extractor = req.get("pre_extractor", [])
        if isinstance(pre_extractor, str):
            pre_extractor = json.loads(pre_extractor) if pre_extractor else []
        if pre_extractor and state.get("_last_response"):
            extracted = _apply_extractor(pre_extractor, state["_last_response"], state)
            if extracted:
                state.setdefault("qaclan_vars", {}).update(extracted)

        # 3. Pre-script
        pre_script = req.get("pre_script")
        pre_lang = req.get("pre_lang", "js")
        if pre_script:
            pre_context = {"headers": headers, "params": params, "env": env_vars}
            pre_out = _run_script_sandbox(pre_script, pre_lang, pre_context, state_path)
            if pre_out:
                headers.update(pre_out.get("headers", {}))
                params.update(pre_out.get("params", {}))
                state.setdefault("qaclan_vars", {}).update(pre_out.get("state", {}))

        # 4. Build request body
        body_type = req.get("body_type")
        body_raw = req.get("body")
        content = None
        data = None
        files = None

        if body_type == "raw" and body_raw:
            content = resolve_vars(body_raw, env_vars, state).encode()
            if not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = "application/json"
        elif body_type == "form" and body_raw:
            try:
                form_items = json.loads(body_raw)
                data = {item["key"]: resolve_vars(item["value"], env_vars, state)
                        for item in form_items if item.get("enabled", True)}
            except (ValueError, TypeError):
                data = {}
        elif body_type == "graphql" and body_raw:
            try:
                gql = json.loads(body_raw)
                content = json.dumps({
                    "query": resolve_vars(gql.get("query", ""), env_vars, state),
                    "variables": gql.get("variables", {}),
                }).encode()
                for _k in list(headers.keys()):
                    if _k.lower() == "content-type":
                        del headers[_k]
                headers["Content-Type"] = "application/json"
            except (ValueError, TypeError):
                content = body_raw.encode() if body_raw else None

        # 5. Execute HTTP request
        method = req.get("method", "GET").upper()
        timeout_ms = int(req.get("timeout_ms") or 30000)
        follow_redirects = bool(req.get("follow_redirects", 1))

        status_code = None
        response_headers = {}
        response_body = ''
        _body_err = None

        with httpx.Client(
            follow_redirects=follow_redirects,
            timeout=timeout_ms / 1000.0,
        ) as http_client:
            with http_client.stream(
                method, url,
                headers=headers,
                params=params or None,
                content=content,
                data=data,
                files=files,
            ) as response:
                status_code = response.status_code
                response_headers = dict(response.headers)
                try:
                    response.read()
                except Exception as _be:
                    _body_err = str(_be)
                try:
                    response_body = response.text
                except Exception:
                    response_body = ''

        duration_ms = int((time.time() - start_time) * 1000)
        finished_at = datetime.now(timezone.utc).isoformat()

        # Store response for next request's pre-extractor
        state["_last_response"] = response_body

        # 6. Post-extractor (no-code variable extraction)
        state_updates = {}
        post_extractor = req.get("post_extractor", [])
        if isinstance(post_extractor, str):
            post_extractor = json.loads(post_extractor) if post_extractor else []
        if post_extractor:
            extracted = _apply_extractor(post_extractor, response_body, state)
            if extracted:
                state_updates.update(extracted)
                state.setdefault("qaclan_vars", {}).update(extracted)

        # 7. Post-script (runs after extractor so script can override)
        post_script = req.get("post_script")
        post_lang = req.get("post_lang", "js")
        if post_script:
            post_context = {
                "headers": headers,
                "params": params,
                "response_body": response_body,
                "response_headers": response_headers,
                "status_code": status_code,
                "env": env_vars,
            }
            post_out = _run_script_sandbox(post_script, post_lang, post_context, state_path)
            if post_out:
                script_state = post_out.get("state", {})
                state_updates.update(script_state)
                state.setdefault("qaclan_vars", {}).update(script_state)

        # 7. Evaluate assertions
        assertions = req.get("assertions", [])
        if isinstance(assertions, str):
            assertions = json.loads(assertions)
        assertion_results = _evaluate_assertions(assertions, status_code, response_body, response_headers, duration_ms)

        if assertion_results:
            all_passed = all(r["passed"] for r in assertion_results)
        else:
            all_passed = status_code is not None and status_code < 400
        status = "PASSED" if all_passed else "FAILED"

        logger.info("run_api_request: %s %s → %d (%dms) %s",
                    method, url, status_code, duration_ms, status)

        return {
            "status": status,
            "status_code": status_code,
            "url": url,
            "response_body": response_body,
            "response_headers": response_headers,
            "duration_ms": duration_ms,
            "assertion_results": assertion_results,
            "error_message": _body_err,
            "state_updates": state_updates,
            "started_at": started_at,
            "finished_at": finished_at,
        }

    except httpx.TimeoutException as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Request timed out after {timeout_ms}ms"
        logger.error("run_api_request: timeout — %s", msg)
        return {
            "status": "ERROR",
            "status_code": None,
            "url": url,
            "response_body": None,
            "response_headers": {},
            "duration_ms": duration_ms,
            "assertion_results": [],
            "error_message": msg,
            "state_updates": {},
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = str(e)
        logger.error("run_api_request: error — %s", msg)
        return {
            "status": "ERROR",
            "status_code": None,
            "url": url,
            "response_body": None,
            "response_headers": {},
            "duration_ms": duration_ms,
            "assertion_results": [],
            "error_message": msg,
            "state_updates": {},
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
