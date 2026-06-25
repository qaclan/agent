# Import Preview Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace direct-save import flow (HAR, OpenAPI, Postman, Bruno) with a parse-then-review UX identical to the recording flow: upload → backend parses → user sees/selects requests → user clicks Save.

**Architecture:** Four new backend "preview" endpoints parse files and return request lists without writing to DB. A new shared JS component `request-review-modal.js` renders the checkbox list + per-request detail modal + Save action. Each import view is simplified to just file/URL capture, then hands off to the shared modal.

**Tech Stack:** Flask (Python), vanilla JS ES modules, existing `window.showModal` / `window.api` / `window.__qaclanApi.refresh` globals, existing parsers in `cli/api_discovery/`.

## Global Constraints

- No new Python or Node dependencies.
- All JS files are ES modules loaded via dynamic `import()` — no bundler.
- `window.showModal`, `window.closeModal`, `window._toast`, `window._alertDialog`, `window.api` are globals available in every view file.
- Save endpoint is already implemented: `POST /api/discover/save-requests` accepts `{requests, collection_name, include_in_docs}`.
- No automated test suite — verify manually via `python qaclan.py serve --port 7823`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `web/api/routes/discovery.py` | Modify | Add 4 preview endpoints |
| `web/static/api/views/request-review-modal.js` | **Create** | Shared review UI: list + detail + save |
| `web/static/api/views/record-apis-view.js` | Modify | Replace inline `_showCapturedResults` with shared modal |
| `web/static/api/views/har-import-view.js` | Rewrite | Simplified: file pick → preview → shared modal |
| `web/static/api/views/openapi-import-view.js` | Rewrite | Simplified: URL/file → preview → shared modal |
| `web/static/api/views/postman-import-view.js` | Rewrite | Simplified: file → preview → shared modal (Postman + Bruno) |

---

## Task 1: Backend Preview Endpoints

**Files:**
- Modify: `web/api/routes/discovery.py`

**Interfaces:**
- Produces:
  - `POST /api/discover/har/preview` → `{ok: true, requests: [ParsedRequest]}`
  - `POST /api/discover/openapi/preview` → `{ok: true, requests: [ParsedRequest]}`
  - `POST /api/discover/postman/preview` → `{ok: true, requests: [ParsedRequest]}`
  - `POST /api/discover/bruno/preview` → `{ok: true, requests: [ParsedRequest]}`
  - Error: `{ok: false, error: string}`
- `ParsedRequest` shape (from existing parsers): `{method, url, name, headers, params, body, collection_name, assertions?, auth_config?, description?}`

**Context:** The existing parsers (`har_parser.parse_har`, `openapi_parser.parse_openapi`, `postman_parser.parse_postman`, `bruno_parser.parse_bruno`) all return `list[dict]`. Preview endpoints just call the parser and return the list — no `_save_requests` call.

- [ ] **Step 1: Add the 4 preview routes to `web/api/routes/discovery.py`**

Add these 4 routes after the existing `discover_har` route (around line 43). Each route is a parse-only twin of its saving counterpart:

```python
@bp.route("/api/discover/har/preview", methods=["POST"])
def discover_har_preview():
    """Parse HAR file and return request list without saving."""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        har_json = json.loads(f.read().decode("utf-8"))
        from cli.api_discovery.har_parser import parse_har
        requests_list = parse_har(har_json)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_har_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/openapi/preview", methods=["POST"])
def discover_openapi_preview():
    """Parse OpenAPI spec (file or URL) and return request list without saving."""
    try:
        from cli.api_discovery.openapi_parser import parse_openapi
        if request.files.get("file"):
            f = request.files["file"]
            raw = f.read().decode("utf-8")
            if f.filename.endswith(".yaml") or f.filename.endswith(".yml"):
                import yaml
                spec = yaml.safe_load(raw)
            else:
                spec = json.loads(raw)
        else:
            data = request.get_json(force=True) or {}
            url = data.get("url", "")
            if not url:
                return jsonify({"ok": False, "error": "Provide 'url' or upload a file"}), 400
            import httpx
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            spec = resp.json() if "json" in ct else __import__("yaml").safe_load(resp.text)
        requests_list = parse_openapi(spec)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_openapi_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/postman/preview", methods=["POST"])
def discover_postman_preview():
    """Parse Postman collection file and return request list without saving."""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        collection_json = json.loads(f.read().decode("utf-8"))
        from cli.api_discovery.postman_parser import parse_postman
        requests_list = parse_postman(collection_json)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_postman_preview")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/bruno/preview", methods=["POST"])
def discover_bruno_preview():
    """Parse .bru files and return request list without saving."""
    try:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "error": "No files uploaded (field: 'files')"}), 400
        from cli.api_discovery.bruno_parser import parse_bruno
        requests_list = []
        for f in files:
            parsed = parse_bruno(f.read().decode("utf-8"))
            for req in parsed:
                if req.get("name") in ("Imported Request", "", None):
                    req["name"] = f.filename.replace(".bru", "")
            requests_list.extend(parsed)
        return jsonify({"ok": True, "requests": requests_list})
    except Exception as e:
        logger.exception("discover_bruno_preview")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Manual smoke test**

Start server: `python qaclan.py serve --port 7823`

Test HAR preview with curl (replace path):
```bash
curl -s -X POST http://localhost:7823/api/discover/har/preview \
  -F "file=@/path/to/test.har" | python3 -m json.tool | head -40
```
Expected: `{"ok": true, "requests": [...]}` with method/url fields visible.

- [ ] **Step 3: Commit**

```bash
git add web/api/routes/discovery.py
git commit -m "feat: add parse-only preview endpoints for all import types"
```

---

## Task 2: Shared Request Review Modal

**Files:**
- Create: `web/static/api/views/request-review-modal.js`

**Interfaces:**
- Produces: `export function showRequestReviewModal(requests, defaultCollectionName)`
  - `requests`: `Array<{method, url, name?, headers?, params?, body?, collection_name?, description?}>`
  - `defaultCollectionName`: `string` — pre-fills the collection name input
  - Internally calls `window.api('POST', '/discover/save-requests', {...})` then `window.__qaclanApi?.refresh?.()` and `window._toast(...)`

- [ ] **Step 1: Create `web/static/api/views/request-review-modal.js`**

```javascript
function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function _fmt(val) {
  if (!val) return '';
  if (typeof val === 'string') {
    try { return JSON.stringify(JSON.parse(val), null, 2); } catch { return val; }
  }
  try { return JSON.stringify(val, null, 2); } catch { return String(val); }
}

function _kvTable(data) {
  if (!data) return '<em style="color:var(--text-muted);font-size:12px">None</em>';
  const entries = Array.isArray(data)
    ? data.map(h => [h.name ?? h.key ?? '', h.value ?? ''])
    : Object.entries(data);
  if (!entries.length) return '<em style="color:var(--text-muted);font-size:12px">None</em>';
  return `<table style="width:100%;border-collapse:collapse;font-size:12px;">
    ${entries.map(([k, v]) => `
      <tr>
        <td style="padding:3px 8px 3px 0;color:var(--text-muted);white-space:nowrap;vertical-align:top;">${_esc(k)}</td>
        <td style="padding:3px 0;word-break:break-all;">${_esc(String(v ?? ''))}</td>
      </tr>`).join('')}
  </table>`;
}

function _showDetail(req) {
  const body = `
    <div style="font-size:13px;">
      <div style="margin-bottom:10px;">
        <span class="method-badge method-${_esc(req.method)}" style="font-size:11px;padding:2px 7px;">${_esc(req.method)}</span>
        <code style="font-size:12px;word-break:break-all;margin-left:6px;">${_esc(req.url)}</code>
      </div>
      ${req.description ? `<p style="font-size:12px;color:var(--text-muted);margin:0 0 12px">${_esc(req.description)}</p>` : ''}
      <div style="margin-bottom:12px;">
        <p class="form-label" style="margin-bottom:4px">Headers</p>
        ${_kvTable(req.headers)}
      </div>
      <div style="margin-bottom:12px;">
        <p class="form-label" style="margin-bottom:4px">Query Params</p>
        ${_kvTable(req.params)}
      </div>
      <div style="margin-bottom:12px;">
        <p class="form-label" style="margin-bottom:4px">Request Body</p>
        ${req.body
          ? `<pre style="margin:0;font-size:11px;background:var(--bg-secondary);padding:8px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;">${_esc(_fmt(req.body))}</pre>`
          : '<em style="color:var(--text-muted);font-size:12px">None</em>'}
      </div>
      ${req.assertions?.length ? `
      <div>
        <p class="form-label" style="margin-bottom:4px">Assertions</p>
        <ul style="margin:0;padding-left:16px;font-size:12px;color:var(--text-muted)">
          ${req.assertions.map(a => `<li>${_esc(typeof a === 'string' ? a : JSON.stringify(a))}</li>`).join('')}
        </ul>
      </div>` : ''}
    </div>`;

  window.showModal(req.name || req.url || 'Request Detail', body, [
    { label: 'Close', cls: 'btn-ghost', action: window.closeModal },
  ], null, 'md');
}

export function showRequestReviewModal(requests, defaultCollectionName) {
  if (!requests?.length) {
    window._alertDialog('No requests found in this file.');
    return;
  }

  const indexedRequests = requests.map((r, i) => ({ ...r, _idx: i }));

  function _renderList(listEl) {
    listEl.innerHTML = indexedRequests.map(r => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);font-size:12px;">
        <input type="checkbox" id="rev-req-${r._idx}" checked>
        <label for="rev-req-${r._idx}" style="flex:1;cursor:pointer;word-break:break-all;min-width:0;">
          <span class="method-badge method-${_esc(r.method)}" style="font-size:10px;padding:1px 5px;">${_esc(r.method)}</span>
          ${_esc(r.name || r.url.replace(/\?.*/, ''))}
          <span style="color:var(--text-muted);margin-left:4px;font-size:10px;">${_esc(r.url.replace(/\?.*/, ''))}</span>
        </label>
        <button type="button" class="btn-ghost rev-detail-btn" data-idx="${r._idx}"
          style="font-size:10px;padding:2px 7px;flex-shrink:0;">Details</button>
      </div>`).join('');
  }

  const modalBody = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">
      ${requests.length} request${requests.length !== 1 ? 's' : ''} found. Select which to save:
    </p>
    <div style="display:flex;gap:8px;margin-bottom:6px;">
      <button type="button" class="btn-ghost" id="rev-all" style="font-size:11px;padding:2px 8px;">All</button>
      <button type="button" class="btn-ghost" id="rev-none" style="font-size:11px;padding:2px 8px;">None</button>
    </div>
    <div id="rev-list" style="max-height:260px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:12px;"></div>
    <div style="margin-bottom:10px;">
      <label class="form-label">Save to collection</label>
      <input id="rev-col-name" type="text" class="input-sm" style="width:100%"
        value="${_esc(defaultCollectionName || 'Imported APIs')}">
    </div>
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
      <input type="checkbox" id="rev-include-docs" checked>
      Include in API Documentation
    </label>`;

  window.showModal('Review & Save Requests', modalBody, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Save Selected', cls: 'btn-primary', action: async () => {
      const colName = document.getElementById('rev-col-name')?.value.trim() || 'Imported APIs';
      const selected = indexedRequests.filter(r => document.getElementById(`rev-req-${r._idx}`)?.checked);
      if (!selected.length) { await window._alertDialog('No requests selected.'); return; }
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const data = await window.api('POST', '/discover/save-requests', {
        requests: selected,
        collection_name: colName,
        include_in_docs: includeInDocs,
      });
      window.closeModal();
      if (data.ok) {
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${colName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
  ], null, 'md');

  requestAnimationFrame(() => {
    const listEl = document.getElementById('rev-list');
    if (listEl) {
      _renderList(listEl);
      listEl.addEventListener('click', e => {
        const btn = e.target.closest('.rev-detail-btn');
        if (btn) {
          const idx = parseInt(btn.dataset.idx, 10);
          _showDetail(indexedRequests[idx]);
        }
      });
    }
    document.getElementById('rev-all')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = true));
    document.getElementById('rev-none')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = false));
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/api/views/request-review-modal.js
git commit -m "feat: add shared request review modal for import flows"
```

---

## Task 3: Update Recording Flow to Use Shared Modal

**Files:**
- Modify: `web/static/api/views/record-apis-view.js`

**Context:** `_showCapturedResults(requests, startUrl)` in this file contains the inline review UI (lines 111–207). We replace it with a call to `showRequestReviewModal`. The third-party filter was recording-specific (we had `startUrl`) — it's not relevant for file imports, but we keep it for recording by passing `defaultCollectionName = 'Recorded APIs'`.

Note: the third-party hostname filter in `_showCapturedResults` is recording-specific. We drop it when moving to the shared modal (it was a nice-to-have, not core). The shared modal does not include it.

- [ ] **Step 1: Replace `_showCapturedResults` and add import**

Replace the entire file content with:

```javascript
import { showRequestReviewModal } from './request-review-modal.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showRecordApis() {
  const bodyHTML = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">
      Enter your app URL. The browser will open to this page so you can start interacting immediately.
    </p>
    <label class="form-label">Start URL</label>
    <input id="record-start-url" type="url" class="input-sm" style="width:100%"
      placeholder="https://your-app.com" autocomplete="url">
    <p id="record-url-error" style="color:var(--danger);font-size:12px;margin-top:4px;display:none">
      Enter a valid URL starting with http:// or https://
    </p>`;

  let _sessionId = null;
  let _pollTimer = null;

  window.showModal('Record APIs', bodyHTML, [
    { label: 'Cancel', cls: 'btn-ghost', action: () => { _cleanup(); window.closeModal(); } },
    { label: 'Start Recording', cls: 'btn-primary', action: _onStart },
  ], null, 'md');

  requestAnimationFrame(() => {
    const input = document.getElementById('record-start-url');
    if (input) {
      input.focus();
      input.addEventListener('keydown', e => { if (e.key === 'Enter') _onStart(); });
    }
  });

  function _onStart() {
    const input = document.getElementById('record-start-url');
    const errEl = document.getElementById('record-url-error');
    const url = input ? input.value.trim() : '';
    if (!url || !/^https?:\/\/.+/.test(url)) {
      if (errEl) errEl.style.display = '';
      if (input) input.focus();
      return;
    }
    if (errEl) errEl.style.display = 'none';
    _startRecording(url);
  }

  async function _startRecording(url) {
    const modalBody = document.querySelector('.modal-body');
    if (modalBody) {
      modalBody.innerHTML = `
        <div class="record-status-badge recording">⏺ Recording</div>
        <p style="margin-top:10px;font-size:13px;color:var(--text-muted)">
          Interact with the browser window. XHR and Fetch requests are being captured.
        </p>
        <p style="font-size:12px;color:var(--text-muted);margin-top:4px">
          URL: <code>${_esc(url)}</code>
        </p>
        <p id="record-count" style="font-size:13px;margin-top:8px">Captured: <strong>0</strong> requests</p>`;
    }
    const stopBtn = document.querySelector('.modal-footer .btn-primary');
    if (stopBtn) {
      const newBtn = stopBtn.cloneNode(true);
      newBtn.textContent = 'Stop Recording';
      newBtn.addEventListener('click', _stopRecording);
      stopBtn.parentNode.replaceChild(newBtn, stopBtn);
    }

    const res = await window.api('POST', '/discover/record/start', { url });
    if (!res.ok) {
      const mb = document.querySelector('.modal-body');
      if (mb) mb.innerHTML = `<p style="color:var(--danger)">Failed to start: ${_esc(res.error)}</p>`;
      return;
    }
    _sessionId = res.session_id;
    _pollTimer = setInterval(_pollStatus, 3000);
  }

  async function _pollStatus() {
    if (!_sessionId) return;
    const res = await window.api('GET', `/discover/record/status?session_id=${_sessionId}`);
    if (!res.ok) return;
    if (res.status === 'stopped') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      const badge = document.querySelector('.record-status-badge');
      if (badge) { badge.className = 'record-status-badge stopped'; badge.textContent = '● Stopped (browser closed)'; }
    }
  }

  async function _stopRecording() {
    _cleanup();
    if (!_sessionId) { window.closeModal(); return; }

    const sid = _sessionId;
    _sessionId = null;
    const res = await window.api('POST', '/discover/record/stop', { session_id: sid });
    window.closeModal();

    if (!res.ok || !res.requests?.length) {
      await window._alertDialog('No API requests captured. Make sure you interacted with the app and XHR/Fetch calls were made.');
      return;
    }
    showRequestReviewModal(res.requests, 'Recorded APIs');
  }

  function _cleanup() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }
}
```

- [ ] **Step 2: Test recording flow manually**

In the UI: Discover → Record APIs → enter a URL → Start Recording → Stop Recording → verify review modal appears with checkboxes and Details buttons.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/record-apis-view.js
git commit -m "refactor: use shared request review modal in recording flow"
```

---

## Task 4: Rewrite HAR Import

**Files:**
- Rewrite: `web/static/api/views/har-import-view.js`

**Context:** Current flow does client-side HAR parsing + checkbox list + direct POST to save. New flow: drop zone → POST file to `/api/discover/har/preview` → `showRequestReviewModal`. Collection name now lives inside the review modal (default = filename without `.har`).

- [ ] **Step 1: Rewrite `web/static/api/views/har-import-view.js`**

```javascript
import { showRequestReviewModal } from './request-review-modal.js';

export function showHarImport() {
  const body = `
    <div id="har-drop-zone" style="border:2px dashed var(--border);border-radius:8px;padding:32px;text-align:center;cursor:pointer;">
      <p style="margin:0;color:var(--text-muted)">Drag & drop .har file here, or <strong>click to browse</strong></p>
      <input type="file" id="har-file-input" accept=".har,application/json" style="display:none">
    </div>
    <p id="har-status" style="font-size:12px;color:var(--text-muted);margin-top:8px;display:none"></p>`;

  window.showModal('Import HAR', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  let _selectedFile = null;

  requestAnimationFrame(() => {
    const dropZone = document.getElementById('har-drop-zone');
    const fileInput = document.getElementById('har-file-input');

    dropZone.onclick = () => fileInput.click();
    fileInput.onchange = e => e.target.files[0] && _setFile(e.target.files[0]);
    dropZone.ondragover = e => { e.preventDefault(); dropZone.style.borderColor = 'var(--primary)'; };
    dropZone.ondragleave = () => { dropZone.style.borderColor = 'var(--border)'; };
    dropZone.ondrop = e => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border)';
      if (e.dataTransfer.files[0]) _setFile(e.dataTransfer.files[0]);
    };
  });

  function _setFile(file) {
    _selectedFile = file;
    const status = document.getElementById('har-status');
    if (status) { status.style.display = ''; status.textContent = `Selected: ${file.name}`; }
  }

  async function _doPreview() {
    if (!_selectedFile) { await window._alertDialog('Please select a HAR file first.'); return; }

    const status = document.getElementById('har-status');
    if (status) { status.textContent = 'Parsing…'; status.style.display = ''; }

    const formData = new FormData();
    formData.append('file', _selectedFile);
    let data;
    try {
      const res = await fetch('/api/discover/har/preview', { method: 'POST', body: formData });
      data = await res.json();
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, _selectedFile.name.replace(/\.har$/i, ''));
  }
}
```

- [ ] **Step 2: Test manually**

In the UI: Discover → Import HAR → select a `.har` file → Preview Requests → verify review modal appears with full request list and Details buttons work.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/har-import-view.js
git commit -m "refactor: HAR import now uses parse-preview-save flow"
```

---

## Task 5: Rewrite OpenAPI Import

**Files:**
- Rewrite: `web/static/api/views/openapi-import-view.js`

**Context:** Previous flow directly saved on import. New flow: URL/file → POST to `/api/discover/openapi/preview` → `showRequestReviewModal`. Collection name default = `"Imported APIs"` (user edits in review modal).

- [ ] **Step 1: Rewrite `web/static/api/views/openapi-import-view.js`**

```javascript
import { showRequestReviewModal } from './request-review-modal.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showOpenApiImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Import from URL</label>
      <input id="openapi-url" type="url" class="input-sm" style="width:100%"
        placeholder="https://api.example.com/openapi.json">
    </div>
    <div style="text-align:center;color:var(--text-muted);margin:8px 0;font-size:12px;">— or —</div>
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload file (.json, .yaml)</label>
      <input id="openapi-file" type="file" accept=".json,.yaml,.yml" class="input-sm">
    </div>
    <p id="openapi-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import OpenAPI / Swagger', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const urlInput = document.getElementById('openapi-url');
    const fileInput = document.getElementById('openapi-file');
    const status = document.getElementById('openapi-status');

    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    let data;
    try {
      if (fileInput?.files[0]) {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        const res = await fetch('/api/discover/openapi/preview', { method: 'POST', body: formData });
        data = await res.json();
      } else if (urlInput?.value.trim()) {
        data = await window.api('POST', '/discover/openapi/preview', { url: urlInput.value.trim() });
      } else {
        if (status) status.style.display = 'none';
        await window._alertDialog('Provide a URL or upload a file.');
        return;
      }
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    const defaultName = fileInput?.files[0]
      ? fileInput.files[0].name.replace(/\.(json|yaml|yml)$/i, '')
      : 'OpenAPI Import';
    showRequestReviewModal(data.requests, defaultName);
  }
}
```

- [ ] **Step 2: Test manually**

In the UI: Discover → Import OpenAPI → enter a URL or upload a file → Preview Requests → verify list + details.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/openapi-import-view.js
git commit -m "refactor: OpenAPI import now uses parse-preview-save flow"
```

---

## Task 6: Rewrite Postman + Bruno Import

**Files:**
- Rewrite: `web/static/api/views/postman-import-view.js`

**Context:** File contains both `showPostmanImport` and `showBrunoImportView`. Both get the same treatment: file → preview endpoint → `showRequestReviewModal`. Previous collection-name inputs are removed (now in review modal).

- [ ] **Step 1: Rewrite `web/static/api/views/postman-import-view.js`**

```javascript
import { showRequestReviewModal } from './request-review-modal.js';

export function showPostmanImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload Postman Collection v2.1 (.json)</label>
      <input id="postman-file" type="file" accept=".json" class="input-sm">
    </div>
    <p id="postman-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import Postman Collection', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const fileInput = document.getElementById('postman-file');
    if (!fileInput?.files[0]) { await window._alertDialog('Please select a Postman collection file.'); return; }

    const status = document.getElementById('postman-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    let data;
    try {
      const res = await fetch('/api/discover/postman/preview', { method: 'POST', body: formData });
      data = await res.json();
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, fileInput.files[0].name.replace(/\.json$/i, ''));
  }
}

export function showBrunoImportView() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload .bru files (select multiple)</label>
      <input id="bruno-files" type="file" accept=".bru" multiple class="input-sm">
    </div>
    <p id="bruno-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import Bruno Files', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const fileInput = document.getElementById('bruno-files');
    if (!fileInput?.files.length) { await window._alertDialog('Please select .bru files.'); return; }

    const status = document.getElementById('bruno-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const formData = new FormData();
    for (const f of fileInput.files) formData.append('files', f);
    let data;
    try {
      const res = await fetch('/api/discover/bruno/preview', { method: 'POST', body: formData });
      data = await res.json();
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, 'Bruno Import');
  }
}
```

- [ ] **Step 2: Test both manually**

In the UI:
- Discover → Import Postman Collection → upload a `.json` → Preview Requests → verify review modal
- Discover → Import Bruno Files → upload `.bru` files → Preview Requests → verify review modal

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/postman-import-view.js
git commit -m "refactor: Postman and Bruno imports use parse-preview-save flow"
```

---

## Self-Review

**Spec coverage:**
- ✅ Parse in backend (preview endpoints)
- ✅ List all parsed requests with checkboxes
- ✅ Select / deselect
- ✅ Click request → detail modal (method, URL, headers, params, body)
- ✅ Save Selected → `/discover/save-requests` → refresh + toast
- ✅ Recording flow reuses shared modal
- ✅ All 4 import types covered (HAR, OpenAPI, Postman, Bruno)

**Removed from old imports (intentional):**
- HAR client-side parsing loop (replaced by backend)
- Per-import `collection_name` override fields (now in review modal, same for all)
- Old direct-save `collection_name` params in backend routes (from previous session) — these remain but are now only used by the saving path, not preview

**Placeholder scan:** None found — all code blocks are complete.

**Type consistency:** `showRequestReviewModal(requests, defaultCollectionName)` signature used identically in Tasks 3–6.
