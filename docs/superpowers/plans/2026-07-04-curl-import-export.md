# cURL Import/Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Postman-parity curl copy/paste to the API request editor — a "Copy as cURL" button, paste-a-curl-into-the-URL-box auto-fill, a bulk "Import cURL" dialog, and default secret-redaction on copy (a safety feature Postman lacks).

**Architecture:** A new backend parser (`cli/api_discovery/curl_parser.py`) follows the exact `list[dict]` request shape already used by `postman_parser.py`/`bruno_parser.py`, so it plugs into the existing `/discover/save-requests` + `request-review-modal.js` pipeline with zero changes to either. A new pure client-side builder (`web/static/api/curl-builder.js`) turns live editor state back into a curl string, with no backend round-trip. Both the paste-fill (single request) and bulk dialog (multi request) reuse the one backend parser as their single source of truth.

**Tech Stack:** Flask (Python 3), vanilla JS ES modules (no build step, no framework), existing `window.api`/`window._toast`/`window._confirmDialog` helpers from `web/static/api/api-section.js`.

## Global Constraints

- This repo has **no automated test framework** (no pytest, no jest — confirmed via `requirements.txt` and `find` for test dirs). Do not add one. Verify each unit with a throwaway script run via `python3 /tmp/<name>.py` or `node /tmp/<name>.mjs`, per-task, as specified below.
- Copied curl must keep `{{VAR}}` tokens **literal** — never resolve to real values (confirmed design decision).
- Redact known-sensitive header values by default when copying; provide one explicit "unmasked" action, never the default.
- New backend parser must return the exact same dict shape as `cli/api_discovery/postman_parser.py` (`name, method, url, headers, params, body_type, body, auth_type, auth_config` — see Task 1) so it is a drop-in for `_save_requests()` in `web/api/services/discovery_service.py:13` and `request-review-modal.js` with no changes to either.
- Follow existing patterns exactly: preview routes call parsers directly (no service-layer wrapper needed — confirmed by `discover_postman_preview` at `web/api/routes/discovery.py:192`), and import views mirror `postman-import-view.js`.

---

### Task 1: `curl_parser.py` — backend curl-to-request-dict parser

**Files:**
- Create: `cli/api_discovery/curl_parser.py`

**Interfaces:**
- Produces: `parse_curl(text: str) -> list[dict]`, each dict shaped like `postman_parser.parse_postman`'s output: `{name, method, url, headers: [{key,value,enabled}], params: [{key,value,enabled}], body_type: 'raw'|'form'|'multipart'|'graphql'|None, body: str|None, auth_type: 'none'|'bearer'|'basic'|'api_key', auth_config: dict}`.
- Consumed by: Task 2 (preview route).

- [ ] **Step 1: Write the failing verification script**

Save to `/tmp/verify_curl_parser.py`:

```python
import sys
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")
from cli.api_discovery.curl_parser import parse_curl

# 1. Simple GET with query string
r = parse_curl("curl https://api.example.com/users?page=2&active=true")[0]
assert r["method"] == "GET", r
assert r["url"] == "https://api.example.com/users", r
assert {"key": "page", "value": "2", "enabled": True} in r["params"], r
assert {"key": "active", "value": "true", "enabled": True} in r["params"], r

# 2. POST with headers + --data-raw JSON body, {{VAR}} preserved
cmd = '''curl -X POST https://api.example.com/login \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {{TOKEN}}" \\
  --data-raw '{"user":"a"}' '''
r = parse_curl(cmd)[0]
assert r["method"] == "POST", r
assert r["url"] == "https://api.example.com/login", r
assert {"key": "Content-Type", "value": "application/json", "enabled": True} in r["headers"], r
assert any(h["key"] == "Authorization" and h["value"] == "Bearer {{TOKEN}}" for h in r["headers"]), r
assert r["body_type"] == "raw", r
assert r["body"] == '{"user":"a"}', r

# 3. -u user:pass -> auth_type basic, no literal Authorization header emitted
r = parse_curl("curl -u alice:s3cret https://api.example.com/me")[0]
assert r["auth_type"] == "basic", r
assert r["auth_config"] == {"username": "alice", "password": "s3cret"}, r
assert not any(h["key"].lower() == "authorization" for h in r["headers"]), r

# 4. -F multipart
r = parse_curl('curl -F "avatar=@photo.png" -F "name=bob" https://api.example.com/upload')[0]
assert r["body_type"] == "multipart", r
import json as _json
rows = _json.loads(r["body"])
assert {"key": "avatar", "value": "@photo.png", "enabled": True} in rows, rows
assert {"key": "name", "value": "bob", "enabled": True} in rows, rows

# 5. Multiple curl commands in one paste
cmd2 = "curl https://a.example.com/one\ncurl https://a.example.com/two"
results = parse_curl(cmd2)
assert len(results) == 2, results
assert results[0]["url"] == "https://a.example.com/one", results
assert results[1]["url"] == "https://a.example.com/two", results

# 6. Malformed command is skipped, doesn't crash the batch
cmd3 = 'curl https://a.example.com/good\ncurl --data-raw "unterminated\ncurl https://a.example.com/also-good'
results = parse_curl(cmd3)
urls = [r["url"] for r in results]
assert "https://a.example.com/good" in urls, urls
assert "https://a.example.com/also-good" in urls, urls

print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 /tmp/verify_curl_parser.py`
Expected: `ModuleNotFoundError: No module named 'cli.api_discovery.curl_parser'`

- [ ] **Step 3: Implement `cli/api_discovery/curl_parser.py`**

```python
from __future__ import annotations
import base64
import json
import logging
import re
import shlex
from urllib.parse import urlsplit, urlunsplit, parse_qsl

logger = logging.getLogger("qaclan.curl_parser")

_CONTINUATION_RE = re.compile(r"[\\^]\s*\r?\n")
_LEADING_PROMPT_RE = re.compile(r"^[\$>]\s*")

_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}
_IGNORED_FLAGS_NO_ARG = {
    "--compressed", "-s", "--silent", "-v", "--verbose", "-i", "--include",
    "-k", "--insecure", "-L", "--location", "--http1.1", "--http2", "-#",
    "--progress-bar", "-f", "--fail",
}


def _split_commands(text: str) -> list[str]:
    """Join backslash/caret line continuations, then split into individual
    curl invocations on newlines/&&/;."""
    joined = _CONTINUATION_RE.sub(" ", text.replace("\r\n", "\n"))
    segments = re.split(r"\n|&&|;", joined)
    commands = []
    for seg in segments:
        seg = _LEADING_PROMPT_RE.sub("", seg.strip()).strip()
        if re.match(r"^curl(\.exe)?\b", seg, re.IGNORECASE):
            commands.append(seg)
    return commands


def _parse_one(command: str) -> dict | None:
    tokens = shlex.split(command, posix=True)
    tokens = tokens[1:]  # drop leading 'curl'/'curl.exe'

    method = None
    url = None
    headers: list[dict] = []
    raw_data_parts: list[str] = []
    form_rows: list[dict] = []
    is_multipart = False
    user = None
    cookie = None
    force_query = False

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request"):
            i += 1
            method = tokens[i].upper()
        elif t in ("-H", "--header"):
            i += 1
            key, _, val = tokens[i].partition(":")
            headers.append({"key": key.strip(), "value": val.strip(), "enabled": True})
        elif t in _DATA_FLAGS:
            i += 1
            raw_data_parts.append(tokens[i])
        elif t in ("-F", "--form"):
            i += 1
            is_multipart = True
            key, _, val = tokens[i].partition("=")
            form_rows.append({"key": key.strip(), "value": val.strip(), "enabled": True})
        elif t in ("-u", "--user"):
            i += 1
            user = tokens[i]
        elif t in ("-b", "--cookie"):
            i += 1
            cookie = tokens[i]
        elif t == "-G":
            force_query = True
        elif t in _IGNORED_FLAGS_NO_ARG:
            pass
        elif not t.startswith("-"):
            if url is None:
                url = t
        i += 1

    if not url:
        return None

    split = urlsplit(url)
    params = [
        {"key": k, "value": v, "enabled": True}
        for k, v in parse_qsl(split.query, keep_blank_values=True)
    ]
    clean_url = urlunsplit((split.scheme, split.netloc, split.path, "", ""))

    if cookie:
        headers.append({"key": "Cookie", "value": cookie, "enabled": True})

    auth_type = "none"
    auth_config: dict = {}
    if user:
        username, _, password = user.partition(":")
        auth_type = "basic"
        auth_config = {"username": username, "password": password}

    body_type = None
    body = None
    if is_multipart:
        body_type = "multipart"
        body = json.dumps(form_rows)
    elif raw_data_parts:
        if force_query:
            for part in raw_data_parts:
                for k, v in parse_qsl(part, keep_blank_values=True):
                    params.append({"key": k, "value": v, "enabled": True})
        else:
            body_type = "raw"
            body = "&".join(raw_data_parts) if len(raw_data_parts) > 1 else raw_data_parts[0]

    if not method:
        method = "POST" if (raw_data_parts and not force_query) or is_multipart else "GET"

    return {
        "name": f"{method} {split.path or '/'}",
        "method": method,
        "url": clean_url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": auth_type,
        "auth_config": auth_config,
    }


def parse_curl(text: str) -> list[dict]:
    """Parse one or more curl commands (shell-line-continuation aware) into
    the standard request-dict list used across cli/api_discovery/*_parser.py."""
    results = []
    for command in _split_commands(text):
        try:
            req = _parse_one(command)
            if req:
                results.append(req)
        except Exception:
            logger.warning("parse_curl: skipping unparseable command: %s", command[:120])
    logger.info("parse_curl: extracted %d requests", len(results))
    return results
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 /tmp/verify_curl_parser.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add cli/api_discovery/curl_parser.py
git commit -m "feat: add curl command parser for API request import"
```

---

### Task 2: `POST /api/discover/curl/preview` route

**Files:**
- Modify: `web/api/routes/discovery.py` (add new route near `discover_postman_preview`, `web/api/routes/discovery.py:192`)

**Interfaces:**
- Consumes: `parse_curl` from Task 1.
- Produces: `POST /api/discover/curl/preview` accepting JSON `{curl: string}`, returning `{ok: true, requests: [...]}` on success (same envelope as `discover_postman_preview`) or `{ok: false, error: string}`.

- [ ] **Step 1: Add the route**

Insert directly after the `discover_bruno_preview` function (after `web/api/routes/discovery.py:226`):

```python
@bp.route("/api/discover/curl/preview", methods=["POST"])
def discover_curl_preview():
    """Parse one or more pasted curl commands and return request list without saving."""
    try:
        data = request.get_json(force=True) or {}
        curl_text = data.get("curl", "")
        if not curl_text.strip():
            return jsonify({"ok": False, "error": "No curl command provided"}), 400
        from cli.api_discovery.curl_parser import parse_curl
        requests_list = parse_curl(curl_text)
        if not requests_list:
            return jsonify({"ok": False, "error": "Could not parse any curl command from the input"}), 400
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_curl_preview")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Verify the route manually**

Start the dev server in one terminal: `python qaclan.py serve --port 7823`

In another terminal:
```bash
curl -s -X POST http://localhost:7823/api/discover/curl/preview \
  -H "Content-Type: application/json" \
  -d '{"curl": "curl -X POST https://api.example.com/login -H \"Content-Type: application/json\" --data-raw \"{\\\"a\\\":1}\""}'
```
Expected: JSON with `"ok": true` and a `"requests"` array containing one object with `"method": "POST"`, `"url": "https://api.example.com/login"`, `"body_type": "raw"`.

Also verify the error path:
```bash
curl -s -X POST http://localhost:7823/api/discover/curl/preview \
  -H "Content-Type: application/json" -d '{"curl": "not a curl command"}'
```
Expected: `{"ok": false, "error": "Could not parse any curl command from the input"}`

- [ ] **Step 3: Commit**

```bash
git add web/api/routes/discovery.py
git commit -m "feat: add curl preview endpoint for import flows"
```

---

### Task 3: Bulk "Import cURL" dialog

**Files:**
- Create: `web/static/api/views/curl-import-view.js`
- Modify: `web/static/api/views/discover-modal.js`

**Interfaces:**
- Consumes: `POST /discover/curl/preview` (Task 2), `showRequestReviewModal` (already exported by `web/static/api/views/request-review-modal.js`, used unchanged).
- Produces: `showCurlImport()` export, wired into the discover grid.

- [ ] **Step 1: Create the import view**

`web/static/api/views/curl-import-view.js` — modeled directly on `web/static/api/views/postman-import-view.js`:

```js
import { showRequestReviewModal } from './request-review-modal.js';

export function showCurlImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Paste one or more curl commands</label>
      <textarea id="curl-input" class="input-sm" rows="10" style="width:100%;font-family:var(--font-mono);font-size:12px;"
        placeholder="curl -X POST https://api.example.com/login -H 'Content-Type: application/json' --data-raw '{&quot;user&quot;:&quot;a&quot;}'"></textarea>
    </div>
    <p id="curl-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import cURL', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const input = document.getElementById('curl-input');
    const text = input?.value.trim();
    if (!text) { await window._alertDialog('Please paste at least one curl command.'); return; }

    const status = document.getElementById('curl-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const data = await window.api('POST', '/discover/curl/preview', { curl: text });

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, 'Imported cURL');
  }
}
```

- [ ] **Step 2: Wire it into the discover grid**

In `web/static/api/views/discover-modal.js`, add the import at the top:

```js
import { showCurlImport } from './curl-import-view.js';
```

And add a card entry to the `options` array (after Postman, before Bruno):

```js
    { icon: '⌨️', title: 'Import cURL', desc: 'Paste one or more curl commands', action: showCurlImport },
```

- [ ] **Step 3: Manually verify in the browser**

Run: `python qaclan.py serve --port 7823`, open `http://localhost:7823`, go to API section → Discover APIs → "Import cURL". Paste:
```
curl -X GET https://jsonplaceholder.typicode.com/users/1
```
Click "Preview Requests". Expected: the review modal opens showing one request (`GET https://jsonplaceholder.typicode.com/users/1`), selectable and saveable via the existing "Save Selected" flow.

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/curl-import-view.js web/static/api/views/discover-modal.js
git commit -m "feat: add bulk curl import dialog"
```

---

### Task 4: `curl-builder.js` — pure client-side curl string builder + redaction

**Files:**
- Create: `web/static/api/curl-builder.js`

**Interfaces:**
- Produces: `buildCurlCommand(reqState, opts = {})` where:
  ```
  reqState = {
    method: string,
    url: string,
    params: [{key, value, enabled}],
    headers: [{key, value, enabled}],
    bodyType: 'none'|'raw'|'form'|'multipart'|'graphql',
    body: string,               // used when bodyType is 'raw' or 'graphql'
    formRows: [{key, value, enabled}], // used when bodyType is 'form' or 'multipart'
    authType: 'none'|'bearer'|'basic'|'api_key'|'oauth2',  // already resolved — never 'inherit'
    authConfig: object,
  }
  opts = { reveal: boolean }     // false/omitted = redact known-sensitive values (default)
  ```
  Returns a multi-line curl string.
- Consumed by: Task 5 (editor "Copy as cURL" button).

- [ ] **Step 1: Write the failing verification script**

Save to `/tmp/verify_curl_builder.mjs`:

```js
import { buildCurlCommand } from "/mnt/ext-drive/qaclan/agent/web/static/api/curl-builder.js";

function assert(cond, msg) { if (!cond) throw new Error("FAIL: " + msg); }

// 1. Simple GET with query params
let cmd = buildCurlCommand({
  method: "GET", url: "https://api.example.com/users",
  params: [{ key: "page", value: "2", enabled: true }],
  headers: [], bodyType: "none", body: "", formRows: [],
  authType: "none", authConfig: {},
});
assert(cmd.includes("-X GET"), "missing method");
assert(cmd.includes("https://api.example.com/users?page=2"), "missing query string: " + cmd);

// 2. {{VAR}} tokens kept literal in headers and body
cmd = buildCurlCommand({
  method: "POST", url: "https://api.example.com/login",
  params: [], headers: [{ key: "Authorization", value: "Bearer {{TOKEN}}", enabled: true }],
  bodyType: "raw", body: '{"user":"{{USER}}"}', formRows: [],
  authType: "none", authConfig: {},
});
assert(cmd.includes("Bearer {{TOKEN}}"), "var token was altered: " + cmd);
assert(cmd.includes('{"user":"{{USER}}"}'), "body var token was altered: " + cmd);

// 3. Redaction by default: literal (non-var) bearer token masked
cmd = buildCurlCommand({
  method: "GET", url: "https://api.example.com/me",
  params: [], headers: [{ key: "Authorization", value: "Bearer sk-live-abc123", enabled: true }],
  bodyType: "none", body: "", formRows: [],
  authType: "none", authConfig: {},
});
assert(!cmd.includes("sk-live-abc123"), "secret leaked unmasked by default: " + cmd);
assert(cmd.includes("Bearer ***REDACTED***"), "expected masked bearer format: " + cmd);

// 4. reveal:true bypasses redaction
cmd = buildCurlCommand({
  method: "GET", url: "https://api.example.com/me",
  params: [], headers: [{ key: "Authorization", value: "Bearer sk-live-abc123", enabled: true }],
  bodyType: "none", body: "", formRows: [],
  authType: "none", authConfig: {},
}, { reveal: true });
assert(cmd.includes("sk-live-abc123"), "reveal:true should show real value: " + cmd);

// 5. basic auth -> -u flag, not a header
cmd = buildCurlCommand({
  method: "GET", url: "https://api.example.com/me",
  params: [], headers: [], bodyType: "none", body: "", formRows: [],
  authType: "basic", authConfig: { username: "{{USERNAME}}", password: "{{PASSWORD}}" },
});
assert(cmd.includes("-u '{{USERNAME}}:{{PASSWORD}}'"), "missing -u flag: " + cmd);
assert(!cmd.toLowerCase().includes("authorization:"), "basic auth should not add a header: " + cmd);

// 6. multipart -> -F per row
cmd = buildCurlCommand({
  method: "POST", url: "https://api.example.com/upload",
  params: [], headers: [], bodyType: "multipart", body: "",
  formRows: [{ key: "name", value: "bob", enabled: true }],
  authType: "none", authConfig: {},
});
assert(cmd.includes("-F 'name=bob'"), "missing -F flag: " + cmd);

console.log("ALL PASS");
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node /tmp/verify_curl_builder.mjs`
Expected: `Cannot find module '/mnt/ext-drive/qaclan/agent/web/static/api/curl-builder.js'`

- [ ] **Step 3: Implement `web/static/api/curl-builder.js`**

```js
// Pure, DOM-free curl string builder. No imports — callers resolve
// {authType, authConfig} (never 'inherit') before calling.

const SENSITIVE_HEADER_RE = /(password|secret|token|authorization|api[-_]?key|auth)/i;
const VAR_RE = /\{\{[^}]+\}\}/;

function _shQuote(str) {
  return `'${String(str).replace(/'/g, "'\\''")}'`;
}

function _maskValue(key, value) {
  if (/^cookie$/i.test(key)) {
    return value
      .split(';')
      .map(pair => {
        const [k, v = ''] = pair.trim().split('=');
        return v.length <= 4 ? `${k}=***` : `${k}=${v.slice(0, 2)}***${v.slice(-2)}`;
      })
      .join('; ');
  }
  const schemeMatch = value.match(/^(Bearer|Basic|Digest)\s+/i);
  if (schemeMatch) return `${schemeMatch[1]} ***REDACTED***`;
  return '***REDACTED***';
}

function _redactHeaders(headers, reveal) {
  if (reveal) return headers;
  return headers.map(h => {
    if (SENSITIVE_HEADER_RE.test(h.key) && !VAR_RE.test(h.value)) {
      return { ...h, value: _maskValue(h.key, h.value) };
    }
    return h;
  });
}

function _encodeQueryValue(v) {
  return VAR_RE.test(v) ? v : encodeURIComponent(v);
}

export function buildCurlCommand(reqState, opts = {}) {
  const reveal = !!opts.reveal;
  const params = (reqState.params || []).filter(p => p.enabled !== false && p.key);
  let headers = (reqState.headers || []).filter(h => h.enabled !== false && h.key);

  const lines = [];
  let leadingComment = null;

  const authType = reqState.authType || 'none';
  const authConfig = reqState.authConfig || {};
  let basicAuthFlag = null;

  if (authType === 'bearer') {
    headers = [...headers, { key: 'Authorization', value: `Bearer ${authConfig.token || '{{ACCESS_TOKEN}}'}`, enabled: true }];
  } else if (authType === 'basic') {
    const user = authConfig.username || '{{USERNAME}}';
    const pass = authConfig.password || '{{PASSWORD}}';
    basicAuthFlag = _shQuote(`${user}:${pass}`);
  } else if (authType === 'api_key') {
    const keyName = authConfig.key_name || authConfig.key || 'X-API-Key';
    const keyValue = authConfig.key_value || authConfig.value || '{{API_KEY}}';
    if (authConfig.in === 'query') {
      params.push({ key: keyName, value: keyValue, enabled: true });
    } else {
      headers = [...headers, { key: keyName, value: keyValue, enabled: true }];
    }
  } else if (authType === 'oauth2') {
    leadingComment = '# OAuth2 (client credentials) — token fetched at send time, not included below';
  }

  headers = _redactHeaders(headers, reveal);

  let url = reqState.url || '';
  if (params.length) {
    const qs = params.map(p => `${p.key}=${_encodeQueryValue(p.value ?? '')}`).join('&');
    url += (url.includes('?') ? '&' : '?') + qs;
  }

  lines.push(`curl -X ${reqState.method || 'GET'} ${_shQuote(url)}`);
  headers.forEach(h => lines.push(`-H ${_shQuote(`${h.key}: ${h.value}`)}`));
  if (basicAuthFlag) lines.push(`-u ${basicAuthFlag}`);

  const bodyType = reqState.bodyType || 'none';
  if (bodyType === 'raw' || bodyType === 'graphql') {
    if (reqState.body) lines.push(`--data-raw ${_shQuote(reqState.body)}`);
  } else if (bodyType === 'form') {
    (reqState.formRows || []).filter(r => r.enabled !== false && r.key).forEach(r =>
      lines.push(`--data-urlencode ${_shQuote(`${r.key}=${r.value ?? ''}`)}`));
  } else if (bodyType === 'multipart') {
    (reqState.formRows || []).filter(r => r.enabled !== false && r.key).forEach(r =>
      lines.push(`-F ${_shQuote(`${r.key}=${r.value ?? ''}`)}`));
  }

  const curlCommand = lines.join(' \\\n  ');
  return leadingComment ? `${leadingComment}\n${curlCommand}` : curlCommand;
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `node /tmp/verify_curl_builder.mjs`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add web/static/api/curl-builder.js
git commit -m "feat: add pure curl command builder with secret redaction"
```

---

### Task 5: "Copy as cURL" button in the request editor

**Files:**
- Modify: `web/static/api/views/request-editor-view.js`

**Interfaces:**
- Consumes: `buildCurlCommand` from Task 4.

- [ ] **Step 1: Import the builder**

Near the top of `web/static/api/views/request-editor-view.js` (alongside the other component imports, `web/static/api/views/request-editor-view.js:1-6`):

```js
import { buildCurlCommand } from '../curl-builder.js';
```

- [ ] **Step 2: Add the buttons next to Send**

In the URL bar block (`web/static/api/views/request-editor-view.js:96-99`, right after `urlBar.appendChild(sendBtn);` and before `editor.appendChild(urlBar);`):

```js
  const copyCurlBtn = document.createElement('button');
  copyCurlBtn.type = 'button';
  copyCurlBtn.className = 'btn btn-sm btn-ghost';
  copyCurlBtn.textContent = 'Copy as cURL';
  copyCurlBtn.title = 'Copy this request as a curl command (secrets masked)';
  urlBar.appendChild(copyCurlBtn);

  const copyCurlUnmaskedBtn = document.createElement('button');
  copyCurlUnmaskedBtn.type = 'button';
  copyCurlUnmaskedBtn.className = 'btn btn-sm btn-ghost';
  copyCurlUnmaskedBtn.textContent = '🔓';
  copyCurlUnmaskedBtn.title = 'Copy as curl with real secret values (unmasked) — be careful where you paste this';
  urlBar.appendChild(copyCurlUnmaskedBtn);

  editor.appendChild(urlBar);
```

- [ ] **Step 3: Add the auth-resolution helper and click handlers**

Add this function after `_updateAuthBanner()` is defined (right after `web/static/api/views/request-editor-view.js:674`, i.e. after the `_updateAuthBanner();` initial call), and the click handlers right after it:

```js
  async function _resolveEffectiveAuth() {
    let type = authTypeSelect.value;
    let cfg = {};
    try { cfg = JSON.parse(_authConfigCache); } catch (e) { cfg = {}; }

    if (type !== 'inherit') return { type, config: cfg };

    if (!_collectionAuth && _effectiveCollectionId) {
      const res = await window.api('GET', `/collections/${_effectiveCollectionId}`);
      const col = res && (res.collection || res);
      _collectionAuth = { auth_type: col?.auth_type || 'none', auth_config: col?.auth_config || '{}' };
    }
    const colType = _collectionAuth?.auth_type || 'none';
    let colCfg = {};
    try { colCfg = JSON.parse(_collectionAuth?.auth_config || '{}'); } catch (e) { colCfg = {}; }
    return { type: colType, config: colCfg };
  }

  async function _copyAsCurl(reveal) {
    const effectiveAuth = await _resolveEffectiveAuth();
    const curl = buildCurlCommand({
      method: methodSelect.value,
      url: urlInput.value.trim(),
      params: paramsTable.getRows(),
      headers: headersTable.getRows(),
      bodyType: activeBodyType,
      body: bodyTextarea.value,
      formRows: formBodyTable.getRows(),
      authType: effectiveAuth.type,
      authConfig: effectiveAuth.config,
    }, { reveal });
    try {
      await navigator.clipboard.writeText(curl);
      window._toast(reveal ? 'Copied as cURL (unmasked)' : 'Copied as cURL');
    } catch (e) {
      window._toast("Couldn't copy — check clipboard permissions");
    }
  }

  copyCurlBtn.onclick = () => _copyAsCurl(false);
  copyCurlUnmaskedBtn.onclick = () => _copyAsCurl(true);
```

- [ ] **Step 4: Manually verify in the browser**

Run: `python qaclan.py serve --port 7823`. Open an existing (or new) request in the editor. Set:
- URL: `https://api.example.com/users`, add a query param `page=2`.
- A header `Authorization: Bearer sk-live-abc123` (literal, not a var).
- Body type `raw`, body `{"a": 1}`.

Click "Copy as cURL", paste into a text editor. Expected: multi-line curl with `-X GET`, `?page=2` in the URL, `-H 'Authorization: Bearer ***REDACTED***'`, `--data-raw '{"a": 1}'`.

Click the 🔓 button, paste again. Expected: the same curl but with `Bearer sk-live-abc123` unmasked.

Switch Auth tab to "Basic Auth", fill username/password with `{{USERNAME}}`/`{{PASSWORD}}`, copy again. Expected: `-u '{{USERNAME}}:{{PASSWORD}}'` present, no `Authorization` header.

- [ ] **Step 5: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: add Copy as cURL button to request editor"
```

---

### Task 6: Paste-a-curl-into-the-URL-box smart import

**Files:**
- Modify: `web/static/api/views/request-editor-view.js`

**Interfaces:**
- Consumes: `POST /discover/curl/preview` (Task 2).

- [ ] **Step 1: Add the paste listener**

Right after `urlBar.appendChild(urlInput);` (`web/static/api/views/request-editor-view.js:94`, before the `sendBtn` block), add:

```js
  urlInput.addEventListener('paste', async (e) => {
    const text = (e.clipboardData || window.clipboardData).getData('text');
    if (!/^\s*curl(\.exe)?\s/i.test(text)) return; // not a curl command — let normal paste happen

    e.preventDefault();

    const hasExistingData = urlInput.value.trim() || paramsTable.getRows().length
      || headersTable.getRows().length || bodyTextarea.value.trim();
    if (hasExistingData) {
      const ok = await window._confirmDialog(
        'Replace current request fields with parsed curl?',
        'This will overwrite the URL, params, headers, and body currently in this editor.'
      );
      if (!ok) return;
    }

    const res = await window.api('POST', '/discover/curl/preview', { curl: text });
    if (!res.ok) { window._toast('Could not parse curl: ' + res.error); return; }

    const parsed = res.requests[0];
    methodSelect.value = parsed.method;
    _applyMethodColor();
    urlInput.value = parsed.url;
    paramsTable.setRows(parsed.params || []);
    headersTable.setRows(parsed.headers || []);

    if (parsed.auth_type && parsed.auth_type !== 'none') {
      authTypeSelect.value = parsed.auth_type;
      _authConfigCache = JSON.stringify(parsed.auth_config || {});
      _renderAuthFields(authTypeSelect.value);
      _updateAuthBanner();
    }

    if (parsed.body_type === 'form') _formRows = JSON.parse(parsed.body || '[]');
    if (parsed.body_type === 'multipart') _multipartRows = JSON.parse(parsed.body || '[]');
    bodyTextarea.value = parsed.body || '';
    _setBodyType(parsed.body_type || 'none');

    _syncPathVars();
    window._toast(`Imported from curl${res.requests.length > 1 ? ` (1 of ${res.requests.length} commands — use Import cURL dialog for the rest)` : ''}`);
  });
```

- [ ] **Step 2: Manually verify in the browser**

Run: `python qaclan.py serve --port 7823`. Open a **new** request in the editor. Copy this into the clipboard:
```
curl -X POST https://jsonplaceholder.typicode.com/posts -H "Content-Type: application/json" --data-raw '{"title":"hi"}'
```
Click into the URL box and paste (Ctrl+V / Cmd+V). Expected: method switches to POST, URL becomes `https://jsonplaceholder.typicode.com/posts`, Headers tab shows `Content-Type: application/json`, Body tab shows `raw` selected with `{"title":"hi"}`, a toast "Imported from curl" appears.

Now type some text manually into the URL box first (e.g. `https://foo.com`), then paste the same curl command again. Expected: a confirm dialog appears asking to replace current fields; cancelling leaves the typed URL untouched, confirming replaces it as before.

Paste a plain URL (not a curl command) into the URL box. Expected: normal paste behavior, no interception, no toast.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: auto-parse curl commands pasted into the URL box"
```
