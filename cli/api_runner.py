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
_PATH_PARAM_RE = re.compile(r"\{(?!\{)([^{}]+)\}(?!\})")
_CHARSET_RE = re.compile(r"charset=([\w-]+)", re.IGNORECASE)


def _detect_charset(response_headers: dict) -> str:
    """Best-effort charset from Content-Type header, falling back to utf-8."""
    for key, value in response_headers.items():
        if key.lower() == "content-type":
            match = _CHARSET_RE.search(value)
            if match:
                return match.group(1)
            break
    return "utf-8"


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
    """Replace {{var_name}} in text. Order: state.qaclan_vars → env_vars → empty+warn."""
    if not text:
        return text or ""
    qc_vars = state.get("qaclan_vars", {}) if isinstance(state, dict) else {}

    def _replace(m):
        key = m.group(1).strip()
        if key in qc_vars:
            return str(qc_vars[key])
        if key in env_vars:
            return str(env_vars[key])
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


def _resolve_vars_deep(obj, env_vars: dict, state: dict):
    """Recursively resolve {{var}} in string leaves of a nested dict/list (e.g. GraphQL variables)."""
    if isinstance(obj, str):
        return resolve_vars(obj, env_vars, state)
    if isinstance(obj, dict):
        return {k: _resolve_vars_deep(v, env_vars, state) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_vars_deep(v, env_vars, state) for v in obj]
    return obj


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
        '_output = {"headers": dict(_ctx.get("headers", {})), "params": dict(_ctx.get("params", {})), '
        '"state": {}, "assertions": []}\n'
        "env = _ctx.get('env', {})\n"
        "class _Qc:\n"
        "    def set(self, k, v): _output['state'][k] = v\n"
        "    def set_header(self, k, v): _output['headers'][k] = v\n"
        "    def set_param(self, k, v): _output['params'][k] = v\n"
        "    def get_header(self, k, default=None):\n"
        "        for hk, hv in _output['headers'].items():\n"
        "            if hk.lower() == str(k).lower(): return hv\n"
        "        return default\n"
        "    def get_param(self, k, default=None): return _output['params'].get(k, default)\n"
        "    def expect(self, condition, message='assertion failed'):\n"
        "        _output['assertions'].append({'type': 'script', 'name': message, 'passed': bool(condition)})\n"
        "    def test(self, name, fn):\n"
        "        try:\n"
        "            fn()\n"
        "            _output['assertions'].append({'type': 'script', 'name': name, 'passed': True})\n"
        "        except Exception as e:\n"
        "            _output['assertions'].append({'type': 'script', 'name': name, 'passed': False, 'error': str(e)})\n"
        "qc = _Qc()\n"
        'response_body = _ctx.get("response_body", "")\n'
        'response_headers = _ctx.get("response_headers", {})\n'
        'status_code = _ctx.get("status_code", 0)\n'
        "class _Resp:\n"
        "    def json(s): return json.loads(response_body)\n"
        "    def text(s): return response_body\n"
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
        "const env = _ctx.env || {};\n"
        "const _output = { headers: Object.assign({}, _ctx.headers), params: Object.assign({}, _ctx.params), state: {}, assertions: [] };\n"
        "const qc = {\n"
        "  set:(k,v)=>_output.state[k]=v,\n"
        "  setHeader:(k,v)=>_output.headers[k]=v,\n"
        "  setParam:(k,v)=>_output.params[k]=v,\n"
        "  getHeader:(k,d)=>{ const lk=String(k).toLowerCase(); for(const hk in _output.headers) if(hk.toLowerCase()===lk) return _output.headers[hk]; return d; },\n"
        "  getParam:(k,d)=>Object.prototype.hasOwnProperty.call(_output.params,k)?_output.params[k]:d,\n"
        "  expect:(condition,message)=>{ _output.assertions.push({type:'script', name: message||'assertion failed', passed: !!condition}); },\n"
        "  test:(name,fn)=>{ try { fn(); _output.assertions.push({type:'script', name, passed:true}); } catch(e) { _output.assertions.push({type:'script', name, passed:false, error:String((e && e.message) || e)}); } },\n"
        "};\n"
        "const response = { json:()=>JSON.parse(_ctx.response_body||'null'), text:()=>_ctx.response_body||'', headers:_ctx.response_headers||{}, status:_ctx.status_code||0 };\n"
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

def _values_equal(actual, expected) -> bool:
    """Type-aware equality for the `eq`/`ne` ops.

    `actual` comes from the response (real JSON types: str/int/float/bool/None/
    list/dict). `expected` is whatever was stored on the assertion — usually a
    plain string typed into the UI (the builder no longer coerces it), but a
    hand-edited/imported assertion can hand it any JSON type directly.
    """
    if isinstance(actual, bool):
        if isinstance(expected, bool):
            return actual == expected
        if isinstance(expected, str):
            return expected.strip().lower() == str(actual).lower()
        return False
    if actual is None:
        if expected is None:
            return True
        return isinstance(expected, str) and expected.strip().lower() == "null"
    if isinstance(actual, (int, float)):
        if isinstance(expected, bool):
            return False
        if isinstance(expected, (int, float)):
            return float(actual) == float(expected)
        if isinstance(expected, str):
            try:
                return float(actual) == float(expected)
            except ValueError:
                return False
        return False
    return str(actual) == str(expected)


def _contains(actual, expected) -> bool:
    """Real membership for list/dict `actual` (json_path matches); falls back
    to substring matching for scalars (json_path scalar, header, body_text)."""
    if isinstance(actual, (list, tuple)):
        return any(_values_equal(item, expected) for item in actual)
    if isinstance(actual, dict):
        return (any(_values_equal(k, expected) for k in actual.keys())
                or any(_values_equal(v, expected) for v in actual.values()))
    return str(expected) in str(actual)


def _compare(actual, op: str, expected) -> bool:
    if op == "eq":
        return _values_equal(actual, expected)
    if op == "ne":
        return not _values_equal(actual, expected)
    if op == "lt":
        return float(actual) < float(expected)
    if op == "gt":
        return float(actual) > float(expected)
    if op == "contains":
        return _contains(actual, expected)
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
                match_mode = assertion.get("matchMode", "first")
                result["path"] = path
                if body_json is None:
                    # No JSON body at all: every path trivially has no match.
                    result["actual"] = None
                    result["passed"] = (op == "not_exists")
                else:
                    expr = jp_parse(path)
                    matches = [m.value for m in expr.find(body_json)]
                    present = bool(matches)  # a match on a JSON `null` still counts as present
                    if op in ("exists", "not_exists"):
                        result["actual"] = matches[0] if matches else None
                        result["passed"] = present if op == "exists" else not present
                    elif not present:
                        result["actual"] = None
                        result["passed"] = False
                    elif match_mode == "any":
                        result["actual"] = matches
                        result["passed"] = any(_compare(m, op, expected) for m in matches)
                    elif match_mode == "all":
                        result["actual"] = matches
                        result["passed"] = all(_compare(m, op, expected) for m in matches)
                    else:  # "first" (default) — only the first match is checked
                        result["actual"] = matches[0]
                        result["passed"] = _compare(matches[0], op, expected)

            elif atype == "header":
                key = assertion.get("key", "")
                actual = response_headers.get(key)
                if actual is None:
                    actual = response_headers.get(key.lower())
                result["key"] = key
                result["actual"] = actual
                if actual is None:
                    # Missing header: only not_exists can pass. Don't let eq/
                    # contains/matches stringify None into the literal "None".
                    result["passed"] = (op == "not_exists")
                else:
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
        script_assertions = []
        pre_script = req.get("pre_script")
        pre_lang = req.get("pre_lang", "js")
        if pre_script:
            pre_context = {"headers": headers, "params": params, "env": env_vars}
            pre_out = _run_script_sandbox(pre_script, pre_lang, pre_context, state_path)
            if pre_out:
                headers.update(pre_out.get("headers", {}))
                params.update(pre_out.get("params", {}))
                state.setdefault("qaclan_vars", {}).update(pre_out.get("state", {}))
                script_assertions.extend(pre_out.get("assertions", []))

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
                data = {item["key"]: resolve_vars(item.get("value", ""), env_vars, state)
                        for item in form_items if item.get("enabled", True)}
            except (ValueError, TypeError):
                data = {}
            # A stale Content-Type (e.g. carried over from a multipart import) would
            # override httpx's auto x-www-form-urlencoded header since explicit
            # headers win — strip it so httpx sets the correct one for this body.
            for _k in list(headers.keys()):
                if _k.lower() == "content-type":
                    del headers[_k]
        elif body_type == "multipart" and body_raw:
            try:
                form_items = json.loads(body_raw)
                files = []
                for item in form_items:
                    if not item.get("enabled", True):
                        continue
                    filename = item.get("filename")
                    content_type = item.get("content_type")
                    if item.get("is_file") and item.get("value"):
                        # File fields carry their actual bytes base64-encoded
                        # (attached via the editor's file picker, or imported
                        # from a source that captured real content).
                        try:
                            file_content = base64.b64decode(item["value"])
                        except (ValueError, TypeError):
                            file_content = b""
                    else:
                        value = resolve_vars(item.get("value", ""), env_vars, state)
                        file_content = value.encode()
                    # httpx: (filename, content, content_type) forces multipart
                    # encoding even for plain text fields; filename=None omits
                    # the filename attribute; content_type=None lets httpx guess.
                    # List of (key, tuple) pairs, not a dict — a dict would
                    # collapse repeated field names (e.g. multiple "files"
                    # entries for a bulk upload) down to the last one.
                    files.append((item["key"], (filename, file_content, content_type)))
            except (ValueError, TypeError):
                files = []
            # A captured/stale Content-Type carries the original boundary, which
            # won't match the boundary httpx generates for the re-encoded body.
            for _k in list(headers.keys()):
                if _k.lower() == "content-type":
                    del headers[_k]
        elif body_type == "graphql" and body_raw:
            try:
                gql = json.loads(body_raw)
                content = json.dumps({
                    "query": resolve_vars(gql.get("query", ""), env_vars, state),
                    "variables": _resolve_vars_deep(gql.get("variables", {}), env_vars, state),
                }).encode()
                for _k in list(headers.keys()):
                    if _k.lower() == "content-type":
                        del headers[_k]
                headers["Content-Type"] = "application/json"
            except (ValueError, TypeError):
                content = body_raw.encode() if body_raw else None

        # Framing headers (Content-Length, Transfer-Encoding) must be computed by
        # httpx from the actual body — a stale value carried over from an import
        # or an edited body causes h11 LocalProtocolError ("Too much/little data
        # for declared Content-Length") since httpx trusts an explicit header.
        for _k in list(headers.keys()):
            if _k.lower() in ("content-length", "transfer-encoding"):
                del headers[_k]

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
                body_chunks = []
                try:
                    for chunk in response.iter_bytes():
                        body_chunks.append(chunk)
                except Exception as _be:
                    _body_err = str(_be)
                raw_body = b"".join(body_chunks)
                if raw_body:
                    try:
                        response_body = raw_body.decode(_detect_charset(response_headers), errors="replace")
                    except LookupError:
                        response_body = raw_body.decode("utf-8", errors="replace")

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
                script_assertions.extend(post_out.get("assertions", []))

        # 7. Evaluate assertions
        assertions = req.get("assertions", [])
        if isinstance(assertions, str):
            assertions = json.loads(assertions)
        assertion_results = _evaluate_assertions(assertions, status_code, response_body, response_headers, duration_ms)
        assertion_results.extend(script_assertions)

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
