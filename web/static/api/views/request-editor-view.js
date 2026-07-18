import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';
import { createVarPicker } from '../components/var-picker.js';
import { createInlineVarDrop } from '../components/inline-var-drop.js';
import { createJsonEditor } from '../components/json-editor.js';
import { buildCurlCommand } from '../curl-builder.js';
import { applyVarStyle, tokenSpansIn, escapeHtml } from '../components/var-style.js';
import { attachTokenOverlay } from '../components/var-token-overlay.js';

/**
 * renderRequestEditor(container, requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId)
 * requestId: string|null  (null = new request)
 * defaultCollectionId: string|null  (pre-select collection when creating new)
 * collectionId: string|null  (resolved collection for var loading)
 * collectionEnvName: string|null  (env bound to the collection)
 * defaultFolderId: string|null  (pre-select the folder a new request is created into)
 */
// Module-level — survives across calls, so a stale in-flight render (e.g. an
// earlier sidebar click whose fetch resolves after a later one, from rapid
// clicking through the list) can tell it's been superseded and bail instead
// of overwriting the newer editor's DOM and dirty-tracking hooks out from
// under it.
let _renderGen = 0;

export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null, collectionId = null, collectionEnvName = null, defaultFolderId = null) {
  const myGen = ++_renderGen;
  container.innerHTML = '<div class="text-muted text-sm" style="padding:20px">Loading...</div>';

  let existing = null;
  let examples = [];
  if (requestId) {
    const res = await window.api('GET', `/api-requests/${requestId}`);
    if (myGen !== _renderGen) return; // superseded while this fetch was in flight
    if (res.ok === false) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">${res.error}</p></div>`;
      return;
    }
    existing = res.request;
    const exRes = await window.api('GET', `/api-requests/${requestId}/examples`);
    if (myGen !== _renderGen) return; // superseded while this fetch was in flight
    if (exRes.ok !== false) examples = exRes.examples || [];
  }

  const r = existing || {};
  const _effectiveCollectionId = r.collection_id || collectionId || defaultCollectionId;

  async function getAllVars() {
    const results = [];
    if (collectionEnvName) {
      try {
        const res = await window.api('GET', `/envs/${encodeURIComponent(collectionEnvName)}`);
        const envVars = res.variables || [];
        envVars.forEach(v => results.push({ key: v.key, value: v.value, is_secret: !!v.is_secret, group: 'Environment' }));
      } catch(e) { /* no env */ }
    }
    if (_effectiveCollectionId) {
      try {
        const res = await window.api('GET', `/collections/${_effectiveCollectionId}/vars`);
        (res.vars || []).forEach(v => results.push({ key: v.key, value: v.initial_value || '', is_secret: false, group: 'Collection' }));
      } catch(e) { /* no collection vars */ }
    }
    return results;
  }

  let _knownVarNames = null;
  let _allVarsList = null;
  let _authFieldInputs = [];
  let _authFieldOverlays = [];
  let _scriptTextareaOverlays = [];
  let _bodyFallbackOverlay = null;
  let _extractorNameInputs = [];

  // Extractor "Variable Name" fields hold a bare name (no {{ }}), so they're
  // styled by exact match against known var names rather than token scanning.
  function _styleExtractorNameInput(inp) {
    inp.classList.remove('kv-value--var-ok', 'kv-value--var-missing');
    const name = inp.value.trim();
    if (!name || !_knownVarNames) return;
    inp.classList.add(_knownVarNames.has(name) ? 'kv-value--var-ok' : 'kv-value--var-missing');
  }

  async function _refreshKnownVarNames() {
    const vars = await getAllVars();
    _knownVarNames = new Set(vars.map(v => v.key));
    _allVarsList = vars;
    paramsTable.restyleAll();
    headersTable.restyleAll();
    pathVarsTable.restyleAll();
    formBodyTable.restyleAll();
    multipartBodyTable.restyleAll();
    _authFieldInputs.forEach(inp => applyVarStyle(inp, _knownVarNames));
    _authFieldOverlays.forEach(o => o.refresh());
    _renderUrlTokens();
    _scriptTextareaOverlays.forEach(o => o.refresh());
    _bodyFallbackOverlay?.refresh();
    _extractorNameInputs.forEach(inp => _styleExtractorNameInput(inp));
    assertionBuilder.restyleAll();
    _cmEditor?.refresh?.();
  }

  container.innerHTML = '';

  const editor = document.createElement('div');
  editor.className = 'request-editor';

  // Dirty tracking is event-driven (see the `input`/`change` listeners wired
  // to `editor` near the end of this function) — declared here since a few
  // non-input actions below (body-type switch, curl paste-import) need to
  // call it explicitly.
  let _dirty = false;
  function _markDirty() { _dirty = true; }

  // ── Header: name + save ──
  const header = document.createElement('div');
  header.className = 'req-editor-header';

  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.placeholder = 'Untitled Request';
  nameInput.value = r.name || '';
  header.appendChild(nameInput);

  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-sm btn-ghost';
  saveBtn.textContent = 'Save';
  header.appendChild(saveBtn);
  editor.appendChild(header);

  // ── URL bar ──
  const urlBar = document.createElement('div');
  urlBar.className = 'req-url-bar';

  const methodSelect = document.createElement('select');
  ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].forEach(m => {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    methodSelect.appendChild(opt);
  });
  methodSelect.value = r.method || 'GET';

  function _applyMethodColor() {
    methodSelect.className = 'req-method-select m-' + methodSelect.value;
  }
  _applyMethodColor();
  methodSelect.onchange = _applyMethodColor;
  urlBar.appendChild(methodSelect);

  // contenteditable, not <input> — no overlay here (see git history). Chrome's
  // autofill paints its own text via -webkit-text-fill-color, which bypasses
  // the color:transparent trick the overlay technique depends on, and Chrome
  // ignores autocomplete=off for this field's autofill heuristic. contenteditable
  // isn't an autofill target at all, and lets {{var}} tokens be colored inline
  // (as real child <span>s) without a second stacked element.
  const urlInput = document.createElement('div');
  urlInput.contentEditable = 'true';
  urlInput.spellcheck = false;
  urlInput.className = 'req-url-input';
  urlInput.dataset.placeholder = 'https://api.example.com/endpoint';
  urlBar.appendChild(urlInput);

  function _urlCaretOffset() {
    const sel = window.getSelection();
    if (!sel.rangeCount || !urlInput.contains(sel.anchorNode)) return null;
    const range = sel.getRangeAt(0);
    const pre = range.cloneRange();
    pre.selectNodeContents(urlInput);
    pre.setEnd(range.endContainer, range.endOffset);
    return pre.toString().length;
  }

  function _setUrlCaretOffset(offset) {
    if (offset == null) return;
    const walker = document.createTreeWalker(urlInput, NodeFilter.SHOW_TEXT);
    let remaining = offset;
    let target = null;
    let targetOffset = 0;
    let node;
    while ((node = walker.nextNode())) {
      const len = node.textContent.length;
      if (remaining <= len) { target = node; targetOffset = remaining; break; }
      remaining -= len;
    }
    const range = document.createRange();
    if (target) {
      range.setStart(target, targetOffset);
      range.collapse(true);
    } else {
      range.selectNodeContents(urlInput);
      range.collapse(false);
    }
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  // Renders {{var}} tokens as colored, individually-hoverable (native title
  // tooltip) spans — preserves caret position across the innerHTML rebuild so
  // typing doesn't jump the cursor to the start every keystroke.
  function _renderUrlTokens() {
    const value = urlInput.textContent;
    const caret = document.activeElement === urlInput ? _urlCaretOffset() : null;
    const list = _allVarsList || [];
    let html = '';
    let last = 0;
    tokenSpansIn(value).forEach(({ name, start, end }) => {
      html += escapeHtml(value.slice(last, start));
      const entry = list.find(v => v.key === name);
      const known = _knownVarNames ? _knownVarNames.has(name) : null;
      const cls = known == null ? 'var-tok' : known ? 'var-tok var-tok--ok' : 'var-tok var-tok--missing';
      const title = entry ? `{{${name}}} = ${entry.value}` : `{{${name}}} — not defined`;
      html += `<span class="${cls}" title="${escapeHtml(title)}">${escapeHtml(value.slice(start, end))}</span>`;
      last = end;
    });
    html += escapeHtml(value.slice(last));
    urlInput.innerHTML = html;
    if (caret != null) _setUrlCaretOffset(caret);
  }

  // .value shim — the rest of this file reads/writes urlInput.value like a
  // normal <input>; keep that working unchanged for a contenteditable div.
  Object.defineProperty(urlInput, 'value', {
    get() { return urlInput.textContent; },
    set(v) { urlInput.textContent = v || ''; _renderUrlTokens(); },
  });
  urlInput.value = r.url || '';

  // {{ autocomplete — contenteditable has no .selectionStart/.setSelectionRange,
  // so this can't use watchInput() (built for real <input>/<textarea>); wire the
  // same open/handleKeydown primitives by hand against the caret-offset helpers above.
  const _urlInlineDrop = createInlineVarDrop(getAllVars);
  urlInput.addEventListener('input', _renderUrlTokens);
  urlInput.addEventListener('input', (e) => {
    if (!e.isTrusted) return;
    const val = urlInput.value;
    const caret = _urlCaretOffset();
    if (caret == null) { _urlInlineDrop.close(); return; }
    const before = val.slice(0, caret);
    const openAt = before.lastIndexOf('{{');
    if (openAt !== -1 && !val.slice(openAt + 2).includes('}}')) {
      const partial = before.slice(openAt + 2);
      _urlInlineDrop.open(urlInput, (varToken) => {
        const cv = urlInput.value;
        const cc = _urlCaretOffset() ?? cv.length;
        const cb = cv.slice(0, cc);
        const oa = cb.lastIndexOf('{{');
        const at = oa !== -1 ? oa : cc;
        urlInput.value = cv.slice(0, at) + varToken + cv.slice(cc);
        _setUrlCaretOffset(at + varToken.length);
        urlInput.focus();
      }, partial);
    } else {
      _urlInlineDrop.close();
    }
  });
  urlInput.addEventListener('keydown', (e) => {
    if (_urlInlineDrop.handleKeydown(e)) return;
    if (e.key === 'Enter') e.preventDefault(); // single-line field, no inserted linebreaks
  });

  urlInput.addEventListener('paste', async (e) => {
    const text = (e.clipboardData || window.clipboardData).getData('text');
    if (!/^\s*curl(\.exe)?\s/i.test(text)) {
      // Not a curl command — still force plain-text insertion (contenteditable
      // would otherwise paste the clipboard's HTML formatting).
      e.preventDefault();
      document.execCommand('insertText', false, text.replace(/[\r\n]+/g, ''));
      return;
    }

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
    _syncUrlFromQueryParams();
    _markDirty(); // programmatic field fills below don't fire input/change events
    window._toast(`Imported from curl${res.requests.length > 1 ? ` (1 of ${res.requests.length} commands — use Import cURL dialog for the rest)` : ''}`);
  });

  const sendBtn = document.createElement('button');
  sendBtn.className = 'btn btn-sm btn-primary req-send-btn';
  sendBtn.textContent = 'Send';
  urlBar.appendChild(sendBtn);

  let examplesSelect = null;
  if (examples.length) {
    examplesSelect = document.createElement('select');
    examplesSelect.className = 'req-examples-select';
    examplesSelect.style.cssText = 'font-size:12px;max-width:160px;';
    examplesSelect.title = 'Load a previously captured example';

    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = 'Default values';
    examplesSelect.appendChild(defaultOpt);

    examples.forEach(ex => {
      const opt = document.createElement('option');
      opt.value = ex.id;
      opt.textContent = ex.label;
      examplesSelect.appendChild(opt);
    });
    urlBar.appendChild(examplesSelect);

    // paramsTable, responsePanel, and _setBodyValue are declared further down in this
    // function; this listener only ever runs after the user interacts with the
    // dropdown, by which point the whole function body (and those consts) has run.
    examplesSelect.onchange = () => {
      const chosen = examples.find(ex => ex.id === examplesSelect.value);
      if (!chosen) {
        paramsTable.setRows(r.params || []);
        _setBodyValue(r.body || '');
        responsePanel.el.style.display = 'none';
        return;
      }
      paramsTable.setRows(chosen.params || []);
      _setBodyValue(chosen.body || '');
      responsePanel.show({
        status_code: chosen.response_status,
        duration_ms: null,
        response_body: chosen.response_body,
        response_headers: chosen.response_headers || {},
        assertion_results: [],
        state_updates: {},
      }, { captured: true, label: chosen.label });
    };
  }

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

  // ── Tab bar ──
  const SECTIONS = ['Params', 'Auth', 'Headers', 'Body', 'Pre-Script', 'Post-Script', 'Assertions'];
  const tabBar = document.createElement('div');
  tabBar.className = 'req-tab-bar';
  const sectionContent = document.createElement('div');
  sectionContent.className = 'req-section-content';
  editor.appendChild(tabBar);
  editor.appendChild(sectionContent);

  // ── URL helpers: split into path / query / hash, shared by param + path-var sync ──
  function _splitUrl(raw) {
    const hashIdx = raw.indexOf('#');
    const hash = hashIdx >= 0 ? raw.slice(hashIdx) : '';
    const beforeHash = hashIdx >= 0 ? raw.slice(0, hashIdx) : raw;
    const qIdx = beforeHash.indexOf('?');
    const query = qIdx >= 0 ? beforeHash.slice(qIdx) : '';
    const path = qIdx >= 0 ? beforeHash.slice(0, qIdx) : beforeHash;
    return { path, query, hash };
  }

  function _stripQuery(raw) {
    const { path, hash } = _splitUrl(raw);
    return path + hash;
  }

  // Query string in the URL bar is a display convenience, not a wire value —
  // the resolved request is built server-side from the params table. Only
  // escape the chars that are structurally significant to our own & / =
  // splitting, so {{VAR}} tokens stay readable instead of percent-encoded.
  function _decodeQueryPart(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
  function _encodeQueryPart(s) { return String(s).replace(/[&=#%]/g, c => encodeURIComponent(c)); }

  function _parseQueryString(qs) {
    if (!qs) return [];
    return qs.split('&').filter(Boolean).map(pair => {
      const eq = pair.indexOf('=');
      const rawKey = eq >= 0 ? pair.slice(0, eq) : pair;
      const rawVal = eq >= 0 ? pair.slice(eq + 1) : '';
      return { key: _decodeQueryPart(rawKey), value: _decodeQueryPart(rawVal), enabled: true };
    });
  }

  function _buildQueryString(rows) {
    return rows.filter(r => r.key && r.enabled !== false)
      .map(r => `${_encodeQueryPart(r.key)}=${_encodeQueryPart(r.value || '')}`)
      .join('&');
  }

  // ── KV components ──
  const paramsTable = createKeyValueTable({
    placeholder: { key: 'Parameter', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames,
    getVarsList: () => _allVarsList,
    onChange: () => _syncUrlFromQueryParams(),
  });
  paramsTable.setRows(r.params || []);

  function _syncQueryParamsFromUrl() {
    const { query } = _splitUrl(urlInput.value);
    paramsTable.setRows(_parseQueryString(query.startsWith('?') ? query.slice(1) : query));
  }

  function _syncUrlFromQueryParams() {
    const { path, hash } = _splitUrl(urlInput.value);
    const qs = _buildQueryString(paramsTable.getRows());
    urlInput.value = path + (qs ? '?' + qs : '') + hash;
  }

  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames, getVarsList: () => _allVarsList });
  headersTable.setRows(r.headers || []);

  const authBanner = document.createElement('div');
  authBanner.style.display = 'none';
  const headersWrapper = document.createElement('div');
  headersWrapper.appendChild(authBanner);
  headersWrapper.appendChild(headersTable.el);

  let _collectionAuth = null;

  // ── Path Variables ──
  const pathVarsTable = createKeyValueTable({
    placeholder: { key: 'param', value: 'value or {{VAR}}' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames,
    getVarsList: () => _allVarsList,
    onChange: () => _syncUrlFromPathVars(),
  });
  const pathVarsSection = document.createElement('div');
  {
    const hdr = document.createElement('div');
    hdr.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:8px 0 4px;';
    hdr.textContent = 'Path Variables';
    const hint = document.createElement('p');
    hint.className = 'req-section-hint';
    hint.textContent = 'Synced with {param} segments in the URL — renaming/adding/removing a row updates the URL too. Values support {{VAR}} syntax.';
    pathVarsSection.appendChild(hdr);
    pathVarsSection.appendChild(hint);
    pathVarsSection.appendChild(pathVarsTable.el);
  }

  const queryParamsHdr = document.createElement('div');
  queryParamsHdr.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:12px 0 4px;';
  queryParamsHdr.textContent = 'Query Parameters';

  const paramsWrapper = document.createElement('div');
  paramsWrapper.appendChild(pathVarsSection);
  paramsWrapper.appendChild(queryParamsHdr);
  paramsWrapper.appendChild(paramsTable.el);

  const _storedPathParams = r.path_params || [];

  // Matches single-brace {param} segments, excluding any brace that's part of
  // a {{VAR}} token (even a malformed one missing its closing brace). Safari
  // <16.4 has no lookbehind support, so adjacency is checked manually below
  // instead of via `(?<!\{)`.
  const PATH_VAR_RE = /\{([^{}]+)\}/g;
  let _lastPathKeys = [];

  function _extractPathVarKeys(str) {
    const keys = [];
    for (const m of str.matchAll(PATH_VAR_RE)) {
      if (str[m.index - 1] === '{' || str[m.index + m[0].length] === '}') continue;
      keys.push(m[1]);
    }
    return keys;
  }

  function _syncPathVars() {
    const matches = _extractPathVarKeys(urlInput.value);
    const keys = [...new Set(matches)];
    _lastPathKeys = keys;
    const current = {};
    pathVarsTable.getRows().forEach(row => { current[row.key] = row.value; });
    const stored = {};
    _storedPathParams.forEach(p => { stored[p.key] = p.value; });
    pathVarsTable.setRows(keys.map(key => ({ key, value: current[key] ?? stored[key] ?? '', enabled: true })));
  }

  function _syncUrlFromPathVars() {
    const newKeys = pathVarsTable.getRows().filter(row => row.key).map(row => row.key);
    const { path, query, hash } = _splitUrl(urlInput.value);
    let newPath = path;

    if (newKeys.length === _lastPathKeys.length) {
      _lastPathKeys.forEach((oldKey, i) => {
        const newKey = newKeys[i];
        if (newKey && newKey !== oldKey) newPath = newPath.replace(`{${oldKey}}`, `{${newKey}}`);
      });
    } else if (newKeys.length < _lastPathKeys.length) {
      _lastPathKeys.filter(oldKey => !newKeys.includes(oldKey)).forEach(oldKey => {
        newPath = newPath.includes(`/{${oldKey}}`) ? newPath.replace(`/{${oldKey}}`, '') : newPath.replace(`{${oldKey}}`, '');
      });
    } else {
      newKeys.filter(key => !_lastPathKeys.includes(key)).forEach(key => {
        if (!newPath.includes(`{${key}}`)) newPath += (newPath.endsWith('/') ? '' : '/') + `{${key}}`;
      });
    }

    if (newPath !== path) urlInput.value = newPath + query + hash;
    _lastPathKeys = [...new Set(_extractPathVarKeys(newPath))];
  }

  urlInput.addEventListener('input', () => { _syncPathVars(); _syncQueryParamsFromUrl(); });
  _syncPathVars();
  _syncUrlFromQueryParams(); // reflect params loaded from the saved request in the URL bar

  const assertionBuilder = createAssertionBuilder({ getVarsList: () => _allVarsList });
  assertionBuilder.setAssertions(r.assertions || []);

  // ── Body section ──
  const bodySection = document.createElement('div');
  const BODY_TYPES = ['none', 'raw', 'form', 'multipart', 'graphql'];
  const BODY_TYPE_LABELS = { form: 'x-www-form-urlencoded', multipart: 'form-data/multipart' };
  let activeBodyType = r.body_type || 'none';

  const bodyTypeGroup = document.createElement('div');
  bodyTypeGroup.className = 'req-body-type-group';
  bodyTypeGroup.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:4px;';

  BODY_TYPES.forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'req-body-type-btn';
    btn.textContent = BODY_TYPE_LABELS[t] || t;
    btn.dataset.type = t;
    btn.onclick = () => {
      if (t === activeBodyType) return; // reselecting the current type is a no-op, not an edit
      _markDirty();
      _setBodyType(t);
    };
    bodyTypeGroup.appendChild(btn);
  });

  const _bodyToolbarSpacer = document.createElement('span');
  _bodyToolbarSpacer.style.flex = '1';
  bodyTypeGroup.appendChild(_bodyToolbarSpacer);

  const formatBtn = document.createElement('button');
  formatBtn.type = 'button';
  formatBtn.title = 'Format JSON (Ctrl+Shift+F)';
  formatBtn.style.cssText = 'font-size:11px;padding:3px 8px;border:1px solid var(--border-default);border-radius:4px;background:none;cursor:pointer;color:var(--text-muted);display:none;';
  formatBtn.textContent = 'Format';
  bodyTypeGroup.appendChild(formatBtn);

  const minifyBtn = document.createElement('button');
  minifyBtn.type = 'button';
  minifyBtn.title = 'Minify JSON';
  minifyBtn.style.cssText = 'font-size:11px;padding:3px 8px;border:1px solid var(--border-default);border-radius:4px;background:none;cursor:pointer;color:var(--text-muted);display:none;';
  minifyBtn.textContent = 'Minify';
  bodyTypeGroup.appendChild(minifyBtn);

  const _bodyVarPicker = createVarPicker({ getVars: getAllVars });
  const _bodyInlineDrop = createInlineVarDrop(getAllVars);
  const bodyVarBtn = document.createElement('button');
  bodyVarBtn.type = 'button';
  bodyVarBtn.title = 'Insert variable at cursor';
  bodyVarBtn.style.cssText = 'font-size:11px;padding:3px 8px;border:1px solid var(--border-default);border-radius:4px;background:none;cursor:pointer;color:var(--text-muted);display:none;';
  bodyVarBtn.textContent = '{ }';
  bodyTypeGroup.appendChild(bodyVarBtn);

  // Hidden textarea — source of truth for _save(), kept in sync by CM onChange
  const bodyTextarea = document.createElement('textarea');
  bodyTextarea.className = 'input-sm body-json-editor';
  bodyTextarea.style.cssText = 'width:100%;min-height:180px;font-family:var(--font-mono);font-size:12px;line-height:1.6;margin-top:4px;resize:vertical;tab-size:2;display:none;';
  bodyTextarea.value = r.body || '';
  bodyTextarea.spellcheck = false;

  // CM editor wrapper — shown instead of textarea when CM loads
  const cmWrap = document.createElement('div');
  cmWrap.style.display = 'none';

  // Fallback textarea — shown when CM unavailable (offline)
  const bodyFallback = document.createElement('textarea');
  bodyFallback.className = 'input-sm body-json-editor';
  bodyFallback.style.cssText = 'width:100%;min-height:180px;font-family:var(--font-mono);font-size:12px;line-height:1.6;margin-top:4px;resize:vertical;tab-size:2;';
  bodyFallback.spellcheck = false;
  _bodyFallbackOverlay = attachTokenOverlay(bodyFallback, () => _allVarsList);
  _bodyFallbackOverlay.el.style.display = 'none';

  const jsonErrorEl = document.createElement('div');
  jsonErrorEl.style.cssText = 'display:none;font-size:11px;color:var(--danger,#e53e3e);padding:3px 6px;margin-top:2px;font-family:var(--font-mono);background:color-mix(in srgb,var(--danger,#e53e3e) 6%,transparent);border-radius:4px;';

  let _cmEditor = null; // CodeMirror view instance (null when unavailable or non-raw type)
  let _cmActive = false;

  function _parseBodyWithVarSub(text) {
    const vars = [];
    const subbed = text.replace(/"\{\{[^}]+\}\}"|\{\{[^}]+\}\}/g, (m) => { vars.push(m); return `"__QCVAR_${vars.length - 1}__"`; });
    return { parsed: JSON.parse(subbed), vars };
  }

  function _getBodyValue() {
    if (_cmActive && _cmEditor) return _cmEditor.getValue();
    if (_cmActive) return bodyFallback.value;
    return bodyTextarea.value;
  }

  function _setBodyValue(val) {
    bodyTextarea.value = val; // always keep hidden textarea in sync for _save()
    if (_cmActive && _cmEditor) { _cmEditor.setValue(val); return; }
    if (_cmActive) { bodyFallback.value = val; return; }
  }

  function _validateFallback() {
    const val = bodyFallback.value.trim();
    if (!val) { jsonErrorEl.style.display = 'none'; bodyFallback.style.borderColor = ''; return; }
    try {
      _parseBodyWithVarSub(val);
      jsonErrorEl.style.display = 'none';
      bodyFallback.style.borderColor = 'var(--success-border, #48bb78)';
    } catch(e) {
      jsonErrorEl.textContent = e.message;
      jsonErrorEl.style.display = '';
      bodyFallback.style.borderColor = 'var(--danger, #e53e3e)';
    }
  }

  formatBtn.onclick = () => {
    const val = _getBodyValue().trim();
    if (!val) return;
    try {
      const { parsed, vars } = _parseBodyWithVarSub(val);
      let pretty = JSON.stringify(parsed, null, 2);
      pretty = pretty.replace(/"__QCVAR_(\d+)__"/g, (_, i) => vars[+i] || '"__VAR__"');
      _setBodyValue(pretty);
      if (!_cmEditor) _validateFallback();
    } catch(e) {
      if (!_cmEditor) _validateFallback();
    }
  };

  minifyBtn.onclick = () => {
    const val = _getBodyValue().trim();
    if (!val) return;
    try {
      const { parsed, vars } = _parseBodyWithVarSub(val);
      let minified = JSON.stringify(parsed);
      minified = minified.replace(/"__QCVAR_(\d+)__"/g, (_, i) => vars[+i] || '__VAR__');
      _setBodyValue(minified);
      if (!_cmEditor) _validateFallback();
    } catch(e) {
      if (!_cmEditor) _validateFallback();
    }
  };

  bodyVarBtn.onclick = () => {
    const anchor = _cmActive ? bodyVarBtn : bodyVarBtn;
    _bodyVarPicker.open(anchor, (varToken) => {
      if (_cmActive && _cmEditor) {
        // Insert at current cursor in CM
        const view = _cmEditor;
        // getValue/setValue approach as CM view is opaque here
        const cur = _cmEditor.getValue();
        _cmEditor.setValue(cur + varToken);
        _cmEditor.focus();
      } else {
        const start = bodyFallback.selectionStart;
        const end = bodyFallback.selectionEnd;
        bodyFallback.value = bodyFallback.value.slice(0, start) + varToken + bodyFallback.value.slice(end);
        bodyTextarea.value = bodyFallback.value;
        bodyFallback.setSelectionRange(start + varToken.length, start + varToken.length);
        bodyFallback.focus();
      }
    });
  };

  // Fallback textarea event handlers
  bodyFallback.addEventListener('keydown', e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = bodyFallback.selectionStart, end = bodyFallback.selectionEnd;
      if (s === end) {
        bodyFallback.value = bodyFallback.value.slice(0, s) + '  ' + bodyFallback.value.slice(end);
        bodyFallback.setSelectionRange(s + 2, s + 2);
      } else {
        const before = bodyFallback.value.slice(0, s);
        const sel = bodyFallback.value.slice(s, end);
        const after = bodyFallback.value.slice(end);
        const indented = sel.replace(/^/gm, '  ');
        bodyFallback.value = before + indented + after;
        bodyFallback.setSelectionRange(s, s + indented.length);
      }
    }
    if (e.key === 'F' && (e.ctrlKey || e.metaKey) && e.shiftKey) { e.preventDefault(); formatBtn.click(); }
  });

  bodyFallback.addEventListener('input', (e) => {
    bodyTextarea.value = bodyFallback.value;
    _validateFallback();
  });
  _bodyInlineDrop.watchInput(bodyFallback);

  async function _activateCmEditor(val) {
    cmWrap.innerHTML = '';
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') !== 'light';
    _cmEditor = await createJsonEditor({
      parent: cmWrap,
      value: val,
      isDark,
      onChange: (v) => { bodyTextarea.value = v; }, // keep hidden textarea in sync
      getVarsList: () => _allVarsList,
    });
    if (!_cmEditor) {
      // CM unavailable — show fallback textarea instead
      cmWrap.style.display = 'none';
      bodyFallback.value = val;
      _bodyFallbackOverlay.el.style.display = '';
      jsonErrorEl.style.display = 'none';
    }
  }

  // Form / multipart bodies share the same key-value table widget, but each
  // type keeps its own row set — otherwise switching tabs would show one
  // type's fields under the other's tab.
  let _formRows = [];
  let _multipartRows = [];
  try {
    const parsed = JSON.parse(r.body || '[]');
    if (Array.isArray(parsed)) {
      if (r.body_type === 'multipart') _multipartRows = parsed;
      else if (r.body_type === 'form') _formRows = parsed;
    }
  } catch(e) { /* leave both empty */ }
  const formBodyTable = createKeyValueTable({
    placeholder: { key: 'field', value: 'value' }, varPickerEnabled: true, getVars: getAllVars,
    getKnownVarNames: () => _knownVarNames, getVarsList: () => _allVarsList,
  });
  const multipartBodyTable = createKeyValueTable({
    placeholder: { key: 'field', value: 'value' }, varPickerEnabled: true, getVars: getAllVars, fileFieldsEnabled: true,
    getKnownVarNames: () => _knownVarNames, getVarsList: () => _allVarsList,
  });
  formBodyTable.setRows(_formRows);
  multipartBodyTable.setRows(_multipartRows);
  formBodyTable.el.style.display = 'none';
  multipartBodyTable.el.style.display = 'none';

  // Called once unconditionally at load (line below) to mount the editor for
  // whatever type is already saved, and from the type-button click handler
  // for genuine switches — never called redundantly with the same type.
  function _setBodyType(type) {
    const prevType = activeBodyType;
    if (prevType === 'form') _formRows = formBodyTable.getRows();
    else if (prevType === 'multipart') _multipartRows = multipartBodyTable.getRows();

    activeBodyType = type;
    bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.type === type);
    });
    const isText = type === 'raw' || type === 'graphql';

    if (!isText && _cmEditor) {
      // Leaving text mode — read current value before destroying
      bodyTextarea.value = _cmEditor.getValue();
      _cmEditor.destroy();
      _cmEditor = null;
      cmWrap.style.display = 'none';
      _bodyFallbackOverlay.el.style.display = 'none';
      _cmActive = false;
    }

    if (type === 'form') formBodyTable.setRows(_formRows);
    else if (type === 'multipart') multipartBodyTable.setRows(_multipartRows);
    formBodyTable.el.style.display = type === 'form' ? '' : 'none';
    multipartBodyTable.el.style.display = type === 'multipart' ? '' : 'none';
    bodyVarBtn.style.display = isText ? '' : 'none';
    formatBtn.style.display = isText ? '' : 'none';
    minifyBtn.style.display = isText ? '' : 'none';
    jsonErrorEl.style.display = 'none';

    if (isText) {
      _cmActive = true;
      cmWrap.style.display = '';
      _bodyFallbackOverlay.el.style.display = 'none';
      _activateCmEditor(bodyTextarea.value);
      if (type === 'graphql') bodyFallback.placeholder = '{ "query": "{ users { id name } }" }';
      else bodyFallback.placeholder = '{\n  "key": "value"\n}';
    }
  }

  _setBodyType(activeBodyType);

  bodySection.appendChild(bodyTypeGroup);
  bodySection.appendChild(bodyTextarea);   // hidden — source of truth for _save()
  bodySection.appendChild(cmWrap);
  bodySection.appendChild(_bodyFallbackOverlay.el);
  bodySection.appendChild(jsonErrorEl);
  bodySection.appendChild(formBodyTable.el);
  bodySection.appendChild(multipartBodyTable.el);

  // ── Auth section ──
  const authSection = document.createElement('div');

  const authTypeSelect = document.createElement('select');
  authTypeSelect.className = 'input-sm';
  authTypeSelect.style.marginBottom = '14px';
  const AUTH_LABELS = {
    inherit: collectionId ? 'Inherit from Collection' : 'Inherit from Collection (no collection)',
    none: 'No Auth',
    bearer: 'Bearer Token',
    basic: 'Basic Auth',
    api_key: 'API Key',
    oauth2: 'OAuth 2 / Custom',
  };
  Object.entries(AUTH_LABELS).forEach(([val, label]) => {
    const opt = document.createElement('option');
    opt.value = val; opt.textContent = label;
    authTypeSelect.appendChild(opt);
  });
  authTypeSelect.value = r.auth_type || 'inherit';

  const authFieldsDiv = document.createElement('div');
  authFieldsDiv.className = 'req-auth-grid';

  let _authConfigCache = typeof r.auth_config === 'object' && r.auth_config !== null
    ? JSON.stringify(r.auth_config, null, 2)
    : (r.auth_config || '{}');

  const _authInlineDrop = createInlineVarDrop(getAllVars);

  function _makeField(labelText, placeholder, getValue, setValue) {
    const wrap = document.createElement('div');
    wrap.className = 'req-auth-field';
    const lbl = document.createElement('label');
    lbl.textContent = labelText;
    const inp = document.createElement('input');
    const isSecret = /password|secret/i.test(labelText);
    inp.type = isSecret ? 'password' : 'text';
    // Chrome ignores autocomplete="off" on password fields and pairs them with the
    // nearest preceding text field as a guessed "username" (no <form> needed for
    // this heuristic) — forcing a save-credentials suggestion onto that field.
    // "new-password" is the one value Chrome actually respects to suppress it.
    inp.autocomplete = isSecret ? 'new-password' : 'off';
    inp.className = 'input-sm';
    inp.placeholder = placeholder;
    inp.value = getValue() || '';
    inp.oninput = () => { setValue(inp.value); applyVarStyle(inp, _knownVarNames); };
    applyVarStyle(inp, _knownVarNames);
    _authInlineDrop.watchInput(inp);
    _authFieldInputs.push(inp);
    const overlay = attachTokenOverlay(inp, () => _allVarsList);
    _authFieldOverlays.push(overlay);
    wrap.appendChild(lbl);
    wrap.appendChild(overlay.el);
    return wrap;
  }

  function _renderAuthFields(type) {
    _authInlineDrop.close();
    authFieldsDiv.innerHTML = '';
    _authFieldInputs = [];
    let cfg = {};
    try { cfg = JSON.parse(_authConfigCache); } catch(e) { cfg = {}; }

    if (type === 'inherit') {
      const hint = document.createElement('p');
      hint.className = 'req-section-hint';
      hint.style.cssText = 'color:var(--text-secondary);';
      hint.textContent = collectionId
        ? 'Uses the auth configured on the parent collection. Override by selecting a specific type above.'
        : 'No collection selected — behaves as No Auth.';
      authFieldsDiv.appendChild(hint);
    } else if (type === 'none') {
      const hint = document.createElement('p');
      hint.className = 'req-section-hint';
      hint.textContent = 'No authentication. Requests are sent without credentials.';
      authFieldsDiv.appendChild(hint);
    } else if (type === 'bearer') {
      authFieldsDiv.appendChild(_makeField(
        'Bearer Token', '{{ACCESS_TOKEN}}',
        () => cfg.token || '',
        v => { cfg.token = v; _authConfigCache = JSON.stringify(cfg); }
      ));
    } else if (type === 'basic') {
      authFieldsDiv.appendChild(_makeField(
        'Username', '{{USERNAME}}',
        () => cfg.username || '',
        v => { cfg.username = v; _authConfigCache = JSON.stringify(cfg); }
      ));
      authFieldsDiv.appendChild(_makeField(
        'Password', '{{PASSWORD}}',
        () => cfg.password || '',
        v => { cfg.password = v; _authConfigCache = JSON.stringify(cfg); }
      ));
    } else if (type === 'api_key') {
      authFieldsDiv.appendChild(_makeField(
        'Header / Param Name', 'X-API-Key',
        () => cfg.key_name || '',
        v => { cfg.key_name = v; _authConfigCache = JSON.stringify(cfg); }
      ));
      authFieldsDiv.appendChild(_makeField(
        'Key Value', '{{API_KEY}}',
        () => cfg.key_value || '',
        v => { cfg.key_value = v; _authConfigCache = JSON.stringify(cfg); }
      ));
    } else {
      const hint = document.createElement('p');
      hint.className = 'req-section-hint';
      hint.textContent = 'Enter auth config as JSON. Use {{VAR}} syntax to reference environment variables.';
      authFieldsDiv.appendChild(hint);
      const ta = document.createElement('textarea');
      ta.className = 'input-sm';
      ta.style.cssText = 'width:100%;min-height:100px;font-family:var(--font-mono);font-size:12px;';
      ta.placeholder = '{"token": "{{ACCESS_TOKEN}}"}';
      ta.value = _authConfigCache;
      ta.oninput = () => { _authConfigCache = ta.value; };
      authFieldsDiv.appendChild(ta);
    }
  }

  authTypeSelect.onchange = () => { _renderAuthFields(authTypeSelect.value); _updateAuthBanner(); };
  _renderAuthFields(authTypeSelect.value);
  _refreshKnownVarNames();
  authSection.appendChild(authTypeSelect);
  authSection.appendChild(authFieldsDiv);
  authFieldsDiv.addEventListener('input', _updateAuthBanner);

  function _updateAuthBanner() {
    const type = authTypeSelect.value;
    let cfg = {};
    try { cfg = JSON.parse(_authConfigCache); } catch(e) { cfg = {}; }

    // Remove previous computed row + reset conflicting user rows
    const tbody = headersTable.el.querySelector('tbody');
    tbody.querySelector('tr.kv-computed-row')?.remove();
    tbody.querySelectorAll('tr.kv-row').forEach(tr => {
      tr.style.opacity = '';
      tr.querySelector('.kv-override-warn')?.remove();
    });
    authBanner.innerHTML = '';
    authBanner.style.display = 'none';

    if (type === 'none') return;

    // Resolve locked header name + value
    let lockedName = null, lockedValue = null, sourceLabel = null, sourceClick = null;

    if (type === 'bearer') {
      lockedName = 'Authorization';
      lockedValue = 'Bearer ' + (cfg.token || '{{ACCESS_TOKEN}}');
      sourceLabel = 'Auth tab →';
      sourceClick = () => { tabBar.querySelectorAll('.req-tab').forEach(t => { if (t.textContent === 'Auth') t.click(); }); };
    } else if (type === 'basic') {
      lockedName = 'Authorization';
      lockedValue = 'Basic …';
      sourceLabel = 'Auth tab →';
      sourceClick = () => { tabBar.querySelectorAll('.req-tab').forEach(t => { if (t.textContent === 'Auth') t.click(); }); };
    } else if (type === 'api_key') {
      lockedName = cfg.key_name || null;
      lockedValue = cfg.key_value || '{{API_KEY}}';
      sourceLabel = 'Auth tab →';
      sourceClick = () => { tabBar.querySelectorAll('.req-tab').forEach(t => { if (t.textContent === 'Auth') t.click(); }); };
    } else if (type === 'oauth2') {
      lockedName = 'Authorization';
      lockedValue = 'Bearer … (via token URL)';
      sourceLabel = 'Auth tab →';
      sourceClick = () => { tabBar.querySelectorAll('.req-tab').forEach(t => { if (t.textContent === 'Auth') t.click(); }); };
    } else if (type === 'inherit') {
      if (!_collectionAuth) {
        // Still fetching — show minimal notice only
        authBanner.style.cssText = 'margin-bottom:6px;padding:4px 8px;font-size:11px;color:var(--text-muted);border-radius:4px;background:var(--surface-2,rgba(0,0,0,.04));border:1px solid var(--border-default);';
        authBanner.textContent = '🔒 Auth inherited from collection';
        authBanner.style.display = '';
        return;
      }
      const colType = _collectionAuth.auth_type || 'none';
      if (colType === 'none') return; // collection has no auth — nothing to lock
      let colCfg = {};
      try { colCfg = JSON.parse(_collectionAuth.auth_config || '{}'); } catch(e) { colCfg = {}; }
      sourceLabel = 'Collection auth';
      if (colType === 'bearer') {
        lockedName = 'Authorization';
        lockedValue = 'Bearer ' + (colCfg.token || '{{ACCESS_TOKEN}}');
      } else if (colType === 'basic') {
        lockedName = 'Authorization';
        lockedValue = 'Basic …';
      } else if (colType === 'api_key') {
        lockedName = colCfg.key_name || null;
        lockedValue = colCfg.key_value || '{{API_KEY}}';
      } else if (colType === 'oauth2') {
        lockedName = 'Authorization';
        lockedValue = 'Bearer … (via token URL)';
      }
    }

    if (!lockedName) return;

    // Inject computed read-only row at top of tbody (5 cols: lock | key | value | badge | empty)
    const computedTr = document.createElement('tr');
    computedTr.className = 'kv-computed-row';
    computedTr.title = type === 'inherit'
      ? 'Injected from collection auth — not editable here'
      : 'Injected by Auth tab — edit in Auth tab, not here';

    const tdLock = document.createElement('td');
    tdLock.style.cssText = 'text-align:center;font-size:11px;opacity:.55;';
    tdLock.textContent = '🔒';
    computedTr.appendChild(tdLock);

    const tdKey = document.createElement('td');
    const keyInp = document.createElement('input');
    keyInp.type = 'text'; keyInp.className = 'kv-key input-sm';
    keyInp.value = lockedName; keyInp.readOnly = true; keyInp.tabIndex = -1;
    keyInp.style.cssText = 'opacity:.55;cursor:default;pointer-events:none;';
    tdKey.appendChild(keyInp);
    computedTr.appendChild(tdKey);

    const tdVal = document.createElement('td');
    const valInp = document.createElement('input');
    valInp.type = 'text'; valInp.className = 'kv-value input-sm';
    valInp.value = lockedValue; valInp.readOnly = true; valInp.tabIndex = -1;
    valInp.style.cssText = 'opacity:.55;cursor:default;pointer-events:none;color:var(--text-muted);';
    tdVal.appendChild(valInp);
    computedTr.appendChild(tdVal);

    const tdBadge = document.createElement('td');
    const badge = document.createElement('span');
    badge.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-3,rgba(0,0,0,.08));border-radius:3px;padding:1px 5px;white-space:nowrap;' + (sourceClick ? 'cursor:pointer;' : '');
    badge.textContent = sourceLabel;
    if (sourceClick) { badge.title = 'Click to switch to Auth tab'; badge.onclick = sourceClick; }
    tdBadge.appendChild(badge);
    computedTr.appendChild(tdBadge);

    computedTr.appendChild(document.createElement('td')); // delete col placeholder
    tbody.prepend(computedTr);

    // Mark conflicting enabled user rows (strikethrough + warning)
    tbody.querySelectorAll('tr.kv-row').forEach(tr => {
      const keyEl = tr.querySelector('.kv-key');
      const cbEl = tr.querySelector('.kv-enabled');
      if (!keyEl) return;
      const isEnabled = cbEl ? cbEl.checked : true;
      if (isEnabled && keyEl.value.trim().toLowerCase() === lockedName.toLowerCase()) {
        tr.style.opacity = '.45';
        const valTd = tr.querySelector('.kv-value')?.closest('td');
        if (valTd) {
          const warn = document.createElement('div');
          warn.className = 'kv-override-warn';
          warn.style.cssText = 'font-size:10px;color:var(--warning,#d97706);margin-top:2px;';
          warn.textContent = '⚠ Overridden by ' + (type === 'inherit' ? 'collection auth' : 'Auth tab');
          valTd.appendChild(warn);
        }
      }
    });
  }
  _updateAuthBanner();

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
      url: _stripQuery(urlInput.value.trim()),
      params: paramsTable.getRows(),
      headers: headersTable.getRows(),
      bodyType: activeBodyType,
      body: bodyTextarea.value,
      formRows: activeBodyType === 'multipart' ? multipartBodyTable.getRows() : formBodyTable.getRows(),
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

  // Fetch collection auth in background for inherit resolution
  if (_effectiveCollectionId) {
    window.api('GET', `/collections/${_effectiveCollectionId}`).then(res => {
      const col = res && (res.collection || res);
      _collectionAuth = { auth_type: col.auth_type || 'none', auth_config: col.auth_config || '{}' };
      _updateAuthBanner();
    }).catch(() => { _collectionAuth = { auth_type: 'none', auth_config: '{}' }; });
  }

  // ── Script sections ──
  const _scriptInlineDrop = createInlineVarDrop(getAllVars);
  function makeScriptSection(lang, code, hint) {
    const div = document.createElement('div');

    const hintEl = document.createElement('p');
    hintEl.className = 'req-section-hint';
    hintEl.textContent = hint;
    div.appendChild(hintEl);

    const langRow = document.createElement('div');
    langRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
    const langLabel = document.createElement('span');
    langLabel.style.cssText = 'font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;';
    langLabel.textContent = 'Language:';
    langRow.appendChild(langLabel);

    const langSelect = document.createElement('select');
    langSelect.className = 'input-sm';
    langSelect.style.cssText = 'width:auto;padding:3px 8px;font-size:12px;';
    [['js', 'JavaScript'], ['python', 'Python']].forEach(([v, l]) => {
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = l;
      langSelect.appendChild(opt);
    });
    langSelect.value = lang || 'js';
    langRow.appendChild(langSelect);
    div.appendChild(langRow);

    const textarea = document.createElement('textarea');
    textarea.className = 'input-sm';
    textarea.style.cssText = 'width:100%;min-height:110px;font-family:var(--font-mono);font-size:12px;';
    const _ph = (l) => l === 'python'
      ? 'qc.set("token", response.json()["access_token"])'
      : 'qc.set("token", response.json().access_token)';
    textarea.placeholder = _ph(lang || 'js');
    langSelect.onchange = () => { textarea.placeholder = _ph(langSelect.value); };
    textarea.value = code || '';
    const scriptOverlay = attachTokenOverlay(textarea, () => _allVarsList);
    _scriptTextareaOverlays.push(scriptOverlay);
    div.appendChild(scriptOverlay.el);
    _scriptInlineDrop.watchInput(textarea);

    div._getLang = () => langSelect.value;
    div._getCode = () => textarea.value;
    return div;
  }

  function _renderSchemaTree(schema, path, onLeafClick) {
    const ul = document.createElement('ul');
    ul.style.cssText = `list-style:none;margin:0;padding-left:${path ? '14px' : '0'};`;
    const isArray = Array.isArray(schema);
    const entries = isArray
      ? (schema.length ? [['0', schema[0]]] : [['0', '?']])
      : Object.entries(schema);
    for (const [key, val] of entries) {
      const li = document.createElement('li');
      li.style.cssText = 'padding:1px 0;';
      const displayKey = isArray ? '[item]' : key;
      const currentPath = path ? `${path}.${key}` : key;
      if (val && typeof val === 'object') {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;padding:1px 2px;border-radius:3px;position:relative;';
        row.onmouseenter = () => { row.style.background = 'var(--surface-2)'; addBtn.style.display = 'inline'; };
        row.onmouseleave = () => { row.style.background = ''; addBtn.style.display = 'none'; };
        const arrow = document.createElement('span');
        arrow.style.cssText = 'font-size:9px;color:var(--text-muted);width:10px;';
        arrow.textContent = '▶';
        const keySpan = document.createElement('span');
        keySpan.style.cssText = 'font-family:var(--font-mono);font-size:12px;';
        keySpan.textContent = displayKey;
        const typeTag = document.createElement('span');
        typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
        typeTag.textContent = Array.isArray(val) ? 'array' : 'object';
        const addBtn = document.createElement('span');
        addBtn.style.cssText = 'display:none;font-size:10px;color:var(--primary);margin-left:4px;padding:0 4px;border-radius:3px;background:var(--surface-3,var(--surface-2));';
        addBtn.title = `Add extractor for: ${currentPath}`;
        addBtn.textContent = '+ extract';
        addBtn.onclick = (e) => { e.stopPropagation(); onLeafClick({ path: currentPath, name: '' }); };
        row.appendChild(arrow); row.appendChild(keySpan); row.appendChild(typeTag); row.appendChild(addBtn);
        const children = _renderSchemaTree(val, currentPath, onLeafClick);
        children.style.display = 'none';
        row.onclick = (e) => {
          if (e.target === addBtn) return;
          const open = children.style.display === 'none';
          children.style.display = open ? '' : 'none';
          arrow.textContent = open ? '▼' : '▶';
        };
        li.appendChild(row); li.appendChild(children);
      } else {
        const isNullType = val === 'null' || val === '?';
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;cursor:pointer;padding:1px 2px;border-radius:3px;';
        row.title = isNullType
          ? `${currentPath} — was null during recording; add extractor anyway`
          : `Add extractor for: ${currentPath}`;
        row.onmouseenter = () => row.style.background = 'var(--surface-2)';
        row.onmouseleave = () => row.style.background = '';
        const dot = document.createElement('span');
        dot.style.cssText = `font-size:9px;width:10px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
        dot.textContent = '●';
        const keySpan = document.createElement('span');
        keySpan.style.cssText = `font-family:var(--font-mono);font-size:12px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
        keySpan.textContent = displayKey;
        const typeTag = document.createElement('span');
        typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
        typeTag.textContent = val || 'any';
        row.onclick = () => onLeafClick({ path: currentPath, name: '' });
        row.appendChild(dot); row.appendChild(keySpan); row.appendChild(typeTag);
        li.appendChild(row);
      }
      ul.appendChild(li);
    }
    return ul;
  }

  function makePreScriptSection(lang, code, extractorRules) {
    const container = document.createElement('div');

    const subBar = document.createElement('div');
    subBar.style.cssText = 'display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:14px;';

    const extractorPane = _buildExtractorPane(
      extractorRules || [],
      null,
      'Extract values from the previous request\'s response (JSON path) and inject as variables into this request.'
    );
    const scriptPane = makeScriptSection(
      lang, code,
      'Runs before the request. Use qc.set("var", value) to inject variables, qc.setHeader/setParam plus qc.getHeader/getParam to read/write, env for active environment vars, and qc.expect/qc.test to assert.'
    );

    const paneArea = document.createElement('div');
    paneArea.appendChild(extractorPane);

    [['Extractor', extractorPane], ['Script', scriptPane]].forEach(([label, pane], idx) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = label;
      btn.style.cssText = `background:none;border:none;padding:6px 14px;font-size:12px;cursor:pointer;border-bottom:2px solid ${idx === 0 ? 'var(--primary)' : 'transparent'};color:${idx === 0 ? 'var(--primary)' : 'var(--text-muted)'};font-weight:${idx === 0 ? '600' : '400'};`;
      btn.onclick = () => {
        subBar.querySelectorAll('button').forEach(b => {
          b.style.borderBottomColor = 'transparent';
          b.style.color = 'var(--text-muted)';
          b.style.fontWeight = '400';
        });
        btn.style.borderBottomColor = 'var(--primary)';
        btn.style.color = 'var(--primary)';
        btn.style.fontWeight = '600';
        paneArea.innerHTML = '';
        paneArea.appendChild(pane);
      };
      subBar.appendChild(btn);
    });

    container.appendChild(subBar);
    container.appendChild(paneArea);

    container._getLang = () => scriptPane._getLang();
    container._getCode = () => scriptPane._getCode();
    container._getExtractor = () => extractorPane._getRows();
    return container;
  }

  function makePostScriptSection(lang, code, extractorRules, responseSchema) {
    const container = document.createElement('div');

    // Sub-tab bar
    const subBar = document.createElement('div');
    subBar.style.cssText = 'display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:14px;';

    const extractorPane = _buildExtractorPane(extractorRules || [], responseSchema || null);
    const scriptPane = makeScriptSection(
      lang, code,
      'Runs after the response. Access response.json(), response.text(), response.status, response.headers. Use qc.set("VAR", val) to save variables, qc.getHeader/getParam to read the request that ran, and qc.expect/qc.test to assert.'
    );

    let activePane = extractorPane;
    const paneArea = document.createElement('div');
    paneArea.appendChild(extractorPane);

    [['Extractor', extractorPane], ['Script', scriptPane]].forEach(([label, pane], idx) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = label;
      btn.style.cssText = `background:none;border:none;padding:6px 14px;font-size:12px;cursor:pointer;border-bottom:2px solid ${idx === 0 ? 'var(--primary)' : 'transparent'};color:${idx === 0 ? 'var(--primary)' : 'var(--text-muted)'};font-weight:${idx === 0 ? '600' : '400'};`;
      btn.onclick = () => {
        subBar.querySelectorAll('button').forEach((b, i) => {
          b.style.borderBottomColor = 'transparent';
          b.style.color = 'var(--text-muted)';
          b.style.fontWeight = '400';
        });
        btn.style.borderBottomColor = 'var(--primary)';
        btn.style.color = 'var(--primary)';
        btn.style.fontWeight = '600';
        paneArea.innerHTML = '';
        paneArea.appendChild(pane);
        activePane = pane;
      };
      subBar.appendChild(btn);
    });

    container.appendChild(subBar);
    container.appendChild(paneArea);

    container._getLang = () => scriptPane._getLang();
    container._getCode = () => scriptPane._getCode();
    container._getExtractor = () => extractorPane._getRows();
    return container;
  }

  function _buildExtractorPane(initialRules, responseSchema, hintText) {
    const div = document.createElement('div');
    const _namePicker = createVarPicker({ getVars: getAllVars });
    const _nameDrop = createInlineVarDrop(getAllVars);

    const hint = document.createElement('p');
    hint.className = 'req-section-hint';
    hint.textContent = hintText || 'Extract values from the response JSON and save as variables. Use {{VAR_NAME}} in later requests.';
    div.appendChild(hint);

    // Schema tree (populated after _addRow is defined below)
    let _schemaBodyEl = null;
    if (responseSchema && typeof responseSchema === 'object' && !Array.isArray(responseSchema) && Object.keys(responseSchema).length) {
      const schemaWrap = document.createElement('div');
      schemaWrap.style.cssText = 'margin-bottom:12px;border:1px solid var(--border);border-radius:6px;overflow:hidden;';
      const schemaHeader = document.createElement('div');
      schemaHeader.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:var(--surface-2);font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;cursor:pointer;user-select:none;';
      const toggle = document.createElement('span');
      toggle.textContent = '▼';
      schemaHeader.innerHTML = '<span>Response Schema — click a field to add extractor row</span>';
      schemaHeader.appendChild(toggle);
      _schemaBodyEl = document.createElement('div');
      _schemaBodyEl.style.cssText = 'padding:8px 10px;max-height:200px;overflow-y:auto;';
      schemaHeader.onclick = () => {
        const open = _schemaBodyEl.style.display === 'none';
        _schemaBodyEl.style.display = open ? '' : 'none';
        toggle.textContent = open ? '▼' : '▶';
      };
      schemaWrap.appendChild(schemaHeader);
      schemaWrap.appendChild(_schemaBodyEl);
      div.appendChild(schemaWrap);
    }

    const table = document.createElement('div');
    table.style.cssText = 'border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:8px;';

    const headerRow = document.createElement('div');
    headerRow.style.cssText = 'display:grid;grid-template-columns:2fr 2fr 28px;gap:8px;padding:5px 10px;background:var(--surface-2);font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;';
    headerRow.innerHTML = '<span>JSON Path</span><span>Variable Name</span><span></span>';
    table.appendChild(headerRow);

    const rowsEl = document.createElement('div');
    table.appendChild(rowsEl);
    div.appendChild(table);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-ghost';
    addBtn.style.cssText = 'font-size:12px;';
    addBtn.textContent = '+ Add Variable';
    addBtn.onclick = () => _addRow({});
    div.appendChild(addBtn);

    function _addRow(rule) {
      const row = document.createElement('div');
      row.className = '_extractor-row';
      row.style.cssText = 'display:grid;grid-template-columns:2fr 2fr 28px;gap:8px;padding:5px 10px;border-top:1px solid var(--border);align-items:center;';

      const mk = (ph, val, mono) => {
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.autocomplete = 'off';
        inp.className = 'input-sm';
        inp.placeholder = ph;
        inp.value = val || '';
        inp.style.cssText = `width:100%;font-size:12px;${mono ? 'font-family:var(--font-mono);' : ''}`;
        return inp;
      };

      const pathInp = mk('data.access_token', rule.path, true);
      const nameInp = mk('access_token', rule.name, false);

      function _pickExtractorVar(varToken) {
        nameInp.value = varToken.replace(/^\{\{|\}\}$/g, '');
        _styleExtractorNameInput(nameInp);
        nameInp.focus();
      }
      nameInp.addEventListener('focus', () => _nameDrop.open(nameInp, _pickExtractorVar, nameInp.value));
      nameInp.addEventListener('input', () => {
        _styleExtractorNameInput(nameInp);
        _nameDrop.open(nameInp, _pickExtractorVar, nameInp.value);
      });
      nameInp.addEventListener('keydown', _nameDrop.handleKeydown);
      _extractorNameInputs.push(nameInp);
      _styleExtractorNameInput(nameInp);

      const nameWrap = document.createElement('div');
      nameWrap.style.cssText = 'display:flex;align-items:center;gap:3px;min-width:0;';
      const namePickerBtn = document.createElement('button');
      namePickerBtn.type = 'button';
      namePickerBtn.title = 'Pick existing variable';
      namePickerBtn.style.cssText = 'flex-shrink:0;background:none;border:1px solid var(--border-default);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:10px;color:var(--text-muted);line-height:1.4;';
      namePickerBtn.textContent = '{}';
      namePickerBtn.onclick = () => {
        _namePicker.open(namePickerBtn, (varToken) => {
          nameInp.value = varToken.replace(/^\{\{|\}\}$/g, '');
        });
      };
      nameWrap.appendChild(nameInp);
      nameWrap.appendChild(namePickerBtn);

      const del = document.createElement('button');
      del.type = 'button';
      del.style.cssText = 'background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;padding:0;line-height:1;';
      del.textContent = '×';
      del.onclick = () => row.remove();

      row.appendChild(pathInp);
      row.appendChild(nameWrap);
      row.appendChild(del);
      rowsEl.appendChild(row);
    }

    (initialRules || []).forEach(r => _addRow(r));

    if (_schemaBodyEl) {
      _schemaBodyEl.appendChild(_renderSchemaTree(responseSchema, '', _addRow));
    }

    div._getRows = () => {
      const rows = [];
      rowsEl.querySelectorAll('._extractor-row').forEach(row => {
        const [pathInp, nameInp] = row.querySelectorAll('input');
        const path = pathInp?.value.trim();
        const name = nameInp?.value.trim();
        if (path && name) rows.push({ path, name });
      });
      return rows;
    };

    return div;
  }

  const preScriptSection = makePreScriptSection(
    r.pre_lang, r.pre_script, r.pre_extractor || []
  );
  const postScriptSection = makePostScriptSection(
    r.post_lang, r.post_script, r.post_extractor || [], r.response_schema || null
  );

  const sectionMap = {
    'Params':      paramsWrapper,
    'Headers':     headersWrapper,
    'Body':        bodySection,
    'Auth':        authSection,
    'Pre-Script':  preScriptSection,
    'Post-Script': postScriptSection,
    'Assertions':  assertionBuilder.el,
  };

  let activeSection = 'Params';

  SECTIONS.forEach(name => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'req-tab' + (name === activeSection ? ' active' : '');
    tab.textContent = name;
    tab.onclick = () => {
      tabBar.querySelectorAll('.req-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeSection = name;
      sectionContent.innerHTML = '';
      sectionContent.appendChild(sectionMap[name]);
      if (name === 'Headers') _updateAuthBanner();
    };
    tabBar.appendChild(tab);
  });
  sectionContent.appendChild(sectionMap[activeSection]);

  // ── Response panel ──
  const responsePanel = createResponsePanel({ schema: r.response_schema || null });
  editor.appendChild(responsePanel.el);
  container.appendChild(editor);

  // ── Send ── (always saves first so extractor/scripts changes take effect)
  sendBtn.onclick = async () => {
    sendBtn.disabled = true;
    sendBtn.textContent = 'Saving…';
    try {
      const rid = await _save();
      if (!rid) return;
      sendBtn.textContent = 'Sending…';
      const res = await window.api('POST', `/api-requests/${rid}/send`, {});
      if (res.ok === false) await window._alertDialog('Send error: ' + res.error);
      else responsePanel.show(res.result);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
  };

  // ── Save ──
  // Builds the wire payload from current field state — also used (unsaved)
  // as a dirty-check snapshot, so it must stay side-effect-free.
  function _buildPayload() {
    let parsedAuth = {};
    try { parsedAuth = JSON.parse(_authConfigCache); } catch(e) { parsedAuth = {}; }

    const payload = {
      name: nameInput.value.trim() || 'Unnamed Request',
      method: methodSelect.value,
      url: _stripQuery(urlInput.value.trim()),
      params: paramsTable.getRows(),
      headers: headersTable.getRows(),
      path_params: pathVarsTable.getRows(),
      body_type: activeBodyType !== 'none' ? activeBodyType : null,
      body: activeBodyType === 'form' ? JSON.stringify(formBodyTable.getRows())
        : activeBodyType === 'multipart' ? JSON.stringify(multipartBodyTable.getRows())
        : (activeBodyType !== 'none' ? (bodyTextarea.value || null) : null),
      auth_type: authTypeSelect.value,
      auth_config: parsedAuth,
      pre_lang: preScriptSection._getLang(),
      pre_script: preScriptSection._getCode() || null,
      pre_extractor: preScriptSection._getExtractor(),
      post_lang: postScriptSection._getLang(),
      post_script: postScriptSection._getCode() || null,
      post_extractor: postScriptSection._getExtractor(),
      assertions: assertionBuilder.getAssertions(),
    };
    if (defaultCollectionId) payload.collection_id = defaultCollectionId;
    if (!requestId && defaultFolderId) payload.folder_id = defaultFolderId;
    return payload;
  }

  async function _save() {
    if (assertionBuilder.hasInvalidAssertions()) {
      await window._alertDialog('One or more assertions is missing its expected value.');
      return null;
    }

    const payload = _buildPayload();
    const res = requestId
      ? await window.api('PUT', `/api-requests/${requestId}`, payload)
      : await window.api('POST', '/api-requests', payload);

    if (res.ok === false) { await window._alertDialog('Save failed: ' + res.error); return null; }
    _dirty = false;
    window.__qaclanApi?.refresh?.(res.request?.id || requestId);
    return res.request?.id || requestId;
  }

  saveBtn.onclick = async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    try {
      const id = await _save();
      if (id) saveBtn.textContent = 'Saved ✓';
      else saveBtn.textContent = 'Save';
    } finally {
      saveBtn.disabled = false;
      setTimeout(() => { saveBtn.textContent = 'Save'; }, 2000);
    }
  };

  // ── Dirty tracking — event-driven, not a payload diff. A diff was fragile:
  // any lazily-mounted widget (the CodeMirror body editor, tab remounts that
  // detach/reattach a whole section) could shift the computed payload with
  // zero real edits and falsely flag dirty. A real user edit always fires a
  // native input/change event on the field the user touched, so delegating
  // both at the editor root catches every field without per-widget wiring —
  // and a remount alone never fires either event.
  editor.addEventListener('input', _markDirty);
  editor.addEventListener('change', _markDirty);
  window.__qaclanApi = window.__qaclanApi || {};
  window.__qaclanApi.isCurrentEditorDirty = () => _dirty;
  window.__qaclanApi.getCurrentEditorRequestId = () => requestId;
}
