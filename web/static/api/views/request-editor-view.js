import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';
import { createVarPicker } from '../components/var-picker.js';
import { createInlineVarDrop } from '../components/inline-var-drop.js';
import { createJsonEditor } from '../components/json-editor.js';

/**
 * renderRequestEditor(container, requestId, defaultCollectionId, collectionId, collectionEnvName)
 * requestId: string|null  (null = new request)
 * defaultCollectionId: string|null  (pre-select collection when creating new)
 * collectionId: string|null  (resolved collection for var loading)
 * collectionEnvName: string|null  (env bound to the collection)
 */
export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null, collectionId = null, collectionEnvName = null) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:20px">Loading...</div>';

  let existing = null;
  if (requestId) {
    const res = await window.api('GET', `/api-requests/${requestId}`);
    if (res.ok === false) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">${res.error}</p></div>`;
      return;
    }
    existing = res.request;
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

  container.innerHTML = '';

  const editor = document.createElement('div');
  editor.className = 'request-editor';

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

  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'req-url-input';
  urlInput.placeholder = 'https://api.example.com/endpoint';
  urlInput.value = r.url || '';
  urlBar.appendChild(urlInput);

  const sendBtn = document.createElement('button');
  sendBtn.className = 'btn btn-sm btn-primary req-send-btn';
  sendBtn.textContent = 'Send';
  urlBar.appendChild(sendBtn);
  editor.appendChild(urlBar);

  // ── Tab bar ──
  const SECTIONS = ['Params', 'Auth', 'Headers', 'Body', 'Pre-Script', 'Post-Script', 'Assertions'];
  const tabBar = document.createElement('div');
  tabBar.className = 'req-tab-bar';
  const sectionContent = document.createElement('div');
  sectionContent.className = 'req-section-content';
  editor.appendChild(tabBar);
  editor.appendChild(sectionContent);

  // ── KV components ──
  const paramsTable = createKeyValueTable({ placeholder: { key: 'Parameter', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars });
  paramsTable.setRows(r.params || []);

  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars });
  headersTable.setRows(r.headers || []);

  // ── Path Variables ──
  const pathVarsTable = createKeyValueTable({ placeholder: { key: 'param', value: 'value or {{VAR}}' }, varPickerEnabled: true, getVars: getAllVars });
  const pathVarsSection = document.createElement('div');
  {
    const hdr = document.createElement('div');
    hdr.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:8px 0 4px;';
    hdr.textContent = 'Path Variables';
    const hint = document.createElement('p');
    hint.className = 'req-section-hint';
    hint.textContent = 'Values for {param} segments in the URL. Supports {{VAR}} syntax.';
    pathVarsSection.appendChild(hdr);
    pathVarsSection.appendChild(hint);
    pathVarsSection.appendChild(pathVarsTable.el);
  }
  pathVarsSection.style.display = 'none';

  const queryParamsHdr = document.createElement('div');
  queryParamsHdr.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:12px 0 4px;';
  queryParamsHdr.textContent = 'Query Parameters';

  const paramsWrapper = document.createElement('div');
  paramsWrapper.appendChild(pathVarsSection);
  paramsWrapper.appendChild(queryParamsHdr);
  paramsWrapper.appendChild(paramsTable.el);

  const _storedPathParams = r.path_params || [];

  function _syncPathVars() {
    const matches = [...urlInput.value.matchAll(/\{([^}]+)\}/g)].map(m => m[1]);
    const keys = [...new Set(matches)];
    if (!keys.length) { pathVarsSection.style.display = 'none'; return; }
    pathVarsSection.style.display = '';
    const current = {};
    pathVarsTable.getRows().forEach(row => { current[row.key] = row.value; });
    const stored = {};
    _storedPathParams.forEach(p => { stored[p.key] = p.value; });
    pathVarsTable.setRows(keys.map(key => ({ key, value: current[key] ?? stored[key] ?? '', enabled: true })));
  }

  urlInput.addEventListener('input', _syncPathVars);
  _syncPathVars();

  const assertionBuilder = createAssertionBuilder();
  assertionBuilder.setAssertions(r.assertions || []);

  // ── Body section ──
  const bodySection = document.createElement('div');
  const BODY_TYPES = ['none', 'raw', 'form', 'graphql'];
  let activeBodyType = r.body_type || 'none';

  const bodyTypeGroup = document.createElement('div');
  bodyTypeGroup.className = 'req-body-type-group';
  bodyTypeGroup.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:4px;';

  BODY_TYPES.forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'req-body-type-btn';
    btn.textContent = t;
    btn.dataset.type = t;
    btn.onclick = () => _setBodyType(t);
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
  bodyFallback.style.cssText = 'width:100%;min-height:180px;font-family:var(--font-mono);font-size:12px;line-height:1.6;margin-top:4px;resize:vertical;tab-size:2;display:none;';
  bodyFallback.spellcheck = false;

  const jsonErrorEl = document.createElement('div');
  jsonErrorEl.style.cssText = 'display:none;font-size:11px;color:var(--danger,#e53e3e);padding:3px 6px;margin-top:2px;font-family:var(--font-mono);background:color-mix(in srgb,var(--danger,#e53e3e) 6%,transparent);border-radius:4px;';

  let _cmEditor = null; // CodeMirror view instance (null when unavailable or non-raw type)
  let _cmActive = false;

  function _parseBodyWithVarSub(text) {
    const vars = [];
    const subbed = text.replace(/\{\{([^}]+)\}\}/g, (m) => { vars.push(m); return `"__QCVAR_${vars.length - 1}__"`; });
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
    });
    if (!_cmEditor) {
      // CM unavailable — show fallback textarea instead
      cmWrap.style.display = 'none';
      bodyFallback.value = val;
      bodyFallback.style.display = '';
      jsonErrorEl.style.display = 'none';
    }
  }

  // Form body
  let _formBodyRows = [];
  try {
    const parsed = JSON.parse(r.body || '[]');
    _formBodyRows = Array.isArray(parsed) ? parsed : [];
  } catch(e) { _formBodyRows = []; }
  const formBodyTable = createKeyValueTable({ placeholder: { key: 'field', value: 'value' }, varPickerEnabled: true, getVars: getAllVars });
  formBodyTable.setRows(_formBodyRows);
  formBodyTable.el.style.display = 'none';

  function _setBodyType(type) {
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
      bodyFallback.style.display = 'none';
      _cmActive = false;
    }

    formBodyTable.el.style.display = type === 'form' ? '' : 'none';
    bodyVarBtn.style.display = isText ? '' : 'none';
    formatBtn.style.display = isText ? '' : 'none';
    minifyBtn.style.display = isText ? '' : 'none';
    jsonErrorEl.style.display = 'none';

    if (isText) {
      _cmActive = true;
      cmWrap.style.display = '';
      bodyFallback.style.display = 'none';
      _activateCmEditor(bodyTextarea.value);
      if (type === 'graphql') bodyFallback.placeholder = '{ "query": "{ users { id name } }" }';
      else bodyFallback.placeholder = '{\n  "key": "value"\n}';
    }
  }

  _setBodyType(activeBodyType);

  bodySection.appendChild(bodyTypeGroup);
  bodySection.appendChild(bodyTextarea);   // hidden — source of truth for _save()
  bodySection.appendChild(cmWrap);
  bodySection.appendChild(bodyFallback);
  bodySection.appendChild(jsonErrorEl);
  bodySection.appendChild(formBodyTable.el);

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
    inp.type = /password|secret/i.test(labelText) ? 'password' : 'text';
    inp.className = 'input-sm';
    inp.placeholder = placeholder;
    inp.value = getValue() || '';
    inp.oninput = () => setValue(inp.value);
    _authInlineDrop.watchInput(inp);
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    return wrap;
  }

  function _renderAuthFields(type) {
    _authInlineDrop.close();
    authFieldsDiv.innerHTML = '';
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

  authTypeSelect.onchange = () => _renderAuthFields(authTypeSelect.value);
  _renderAuthFields(authTypeSelect.value);
  authSection.appendChild(authTypeSelect);
  authSection.appendChild(authFieldsDiv);

  // ── Script sections ──
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
    div.appendChild(textarea);

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
      'Runs before the request. Use qc.set("var", value) to inject variables into URL/headers/body.'
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
      'Runs after the response. Access response.json(), response.status, response.headers. Use qc.set("VAR", val) to save variables.'
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
        inp.className = 'input-sm';
        inp.placeholder = ph;
        inp.value = val || '';
        inp.style.cssText = `width:100%;font-size:12px;${mono ? 'font-family:var(--font-mono);' : ''}`;
        return inp;
      };

      const pathInp = mk('data.access_token', rule.path, true);
      const nameInp = mk('access_token', rule.name, false);

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
    'Headers':     headersTable.el,
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
  async function _save() {
    let parsedAuth = {};
    try { parsedAuth = JSON.parse(_authConfigCache); } catch(e) { parsedAuth = {}; }

    const payload = {
      name: nameInput.value.trim() || 'Unnamed Request',
      method: methodSelect.value,
      url: urlInput.value.trim(),
      params: paramsTable.getRows(),
      headers: headersTable.getRows(),
      path_params: pathVarsTable.getRows(),
      body_type: activeBodyType !== 'none' ? activeBodyType : null,
      body: activeBodyType === 'form'
        ? JSON.stringify(formBodyTable.getRows())
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

    const res = requestId
      ? await window.api('PUT', `/api-requests/${requestId}`, payload)
      : await window.api('POST', '/api-requests', payload);

    if (res.ok === false) { await window._alertDialog('Save failed: ' + res.error); return null; }
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
}
