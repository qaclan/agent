import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';
import { createVarPicker } from '../components/var-picker.js';

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

  urlInput.addEventListener('input', _syncPathVars);
  _syncPathVars();

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

  const assertionBuilder = createAssertionBuilder();
  assertionBuilder.setAssertions(r.assertions || []);

  // ── Body section ──
  const bodySection = document.createElement('div');
  const BODY_TYPES = ['none', 'raw', 'form', 'graphql'];
  let activeBodyType = r.body_type || 'none';

  const bodyTypeGroup = document.createElement('div');
  bodyTypeGroup.className = 'req-body-type-group';
  bodyTypeGroup.style.display = 'flex';
  bodyTypeGroup.style.alignItems = 'center';

  BODY_TYPES.forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'req-body-type-btn';
    btn.textContent = t;
    btn.dataset.type = t;
    btn.onclick = () => _setBodyType(t);
    bodyTypeGroup.appendChild(btn);
  });

  // {} insert variable button — visible only for raw/graphql body types
  const _bodyVarPicker = createVarPicker({ getVars: getAllVars });
  const bodyVarBtn = document.createElement('button');
  bodyVarBtn.type = 'button';
  bodyVarBtn.title = 'Insert variable at cursor';
  bodyVarBtn.style.cssText = 'margin-left:auto;font-size:11px;padding:3px 8px;border:1px solid var(--border);border-radius:4px;background:none;cursor:pointer;color:var(--text-muted);';
  bodyVarBtn.textContent = '{ }';
  bodyVarBtn.style.display = 'none';
  bodyVarBtn.onclick = () => {
    _bodyVarPicker.open(bodyVarBtn, (varToken) => {
      const start = bodyTextarea.selectionStart;
      const end = bodyTextarea.selectionEnd;
      bodyTextarea.value = bodyTextarea.value.slice(0, start) + varToken + bodyTextarea.value.slice(end);
      const newPos = start + varToken.length;
      bodyTextarea.setSelectionRange(newPos, newPos);
      bodyTextarea.focus();
    });
  };
  bodyTypeGroup.appendChild(bodyVarBtn);

  const bodyTextarea = document.createElement('textarea');
  bodyTextarea.className = 'input-sm';
  bodyTextarea.style.cssText = 'width:100%;min-height:140px;font-family:var(--font-mono);font-size:12px;margin-top:4px;';
  bodyTextarea.value = r.body || '';
  bodyTextarea.addEventListener('input', () => {
    const val = bodyTextarea.value;
    const caret = bodyTextarea.selectionStart ?? val.length;
    const before = val.slice(0, caret);
    const openAt = before.lastIndexOf('{{');
    if (openAt !== -1 && !before.slice(openAt).includes('}}')) {
      const partial = before.slice(openAt + 2);
      _bodyVarPicker.open(bodyTextarea, (varToken) => {
        const after = val.slice(caret);
        bodyTextarea.value = val.slice(0, openAt) + varToken + after;
        const newPos = openAt + varToken.length;
        bodyTextarea.setSelectionRange(newPos, newPos);
        bodyTextarea.focus();
      }, partial);
    } else {
      _bodyVarPicker.close();
    }
  });

  // Form body — KV table with var picker
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
    bodyTextarea.style.display = (type === 'raw' || type === 'graphql') ? '' : 'none';
    formBodyTable.el.style.display = type === 'form' ? '' : 'none';
    bodyVarBtn.style.display = (type === 'raw' || type === 'graphql') ? '' : 'none';
    if (type === 'graphql') bodyTextarea.placeholder = '{ "query": "{ users { id name } }" }';
    else bodyTextarea.placeholder = '{\n  "key": "value"\n}';
  }

  _setBodyType(activeBodyType);

  bodySection.appendChild(bodyTypeGroup);
  bodySection.appendChild(bodyTextarea);
  bodySection.appendChild(formBodyTable.el);

  // ── Auth section ──
  const authSection = document.createElement('div');

  const authTypeSelect = document.createElement('select');
  authTypeSelect.className = 'input-sm';
  authTypeSelect.style.marginBottom = '14px';
  const AUTH_LABELS = { none: 'No Auth', bearer: 'Bearer Token', basic: 'Basic Auth', api_key: 'API Key', oauth2: 'OAuth 2 / Custom' };
  Object.entries(AUTH_LABELS).forEach(([val, label]) => {
    const opt = document.createElement('option');
    opt.value = val; opt.textContent = label;
    authTypeSelect.appendChild(opt);
  });
  authTypeSelect.value = r.auth_type || 'none';

  const authFieldsDiv = document.createElement('div');
  authFieldsDiv.className = 'req-auth-grid';

  let _authConfigCache = typeof r.auth_config === 'object' && r.auth_config !== null
    ? JSON.stringify(r.auth_config, null, 2)
    : (r.auth_config || '{}');

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
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    return wrap;
  }

  function _renderAuthFields(type) {
    authFieldsDiv.innerHTML = '';
    let cfg = {};
    try { cfg = JSON.parse(_authConfigCache); } catch(e) { cfg = {}; }

    if (type === 'none') {
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
    textarea.placeholder = 'qc.set("token", response.json().access_token)';
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
        addBtn.onclick = (e) => { e.stopPropagation(); onLeafClick({ path: currentPath, name: '', prefix: '' }); };
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
        row.onclick = () => onLeafClick({ path: currentPath, name: '', prefix: '' });
        row.appendChild(dot); row.appendChild(keySpan); row.appendChild(typeTag);
        li.appendChild(row);
      }
      ul.appendChild(li);
    }
    return ul;
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

  function _buildExtractorPane(initialRules, responseSchema) {
    const div = document.createElement('div');

    const hint = document.createElement('p');
    hint.className = 'req-section-hint';
    hint.textContent = 'Extract values from the response JSON and save as variables. Use {{VAR_NAME}} in later requests.';
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
    headerRow.style.cssText = 'display:grid;grid-template-columns:2fr 1.5fr 1fr 28px;gap:8px;padding:5px 10px;background:var(--surface-2);font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;';
    headerRow.innerHTML = '<span>JSON Path</span><span>Variable Name</span><span>Prefix</span><span></span>';
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
      row.style.cssText = 'display:grid;grid-template-columns:2fr 1.5fr 1fr 28px;gap:8px;padding:5px 10px;border-top:1px solid var(--border);align-items:center;';

      const mk = (ph, val, mono) => {
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'input-sm';
        inp.placeholder = ph;
        inp.value = val || '';
        inp.style.cssText = `width:100%;font-size:12px;${mono ? 'font-family:var(--font-mono);' : ''}`;
        return inp;
      };

      const pathInp   = mk('token  or  data.access_token', rule.path, true);
      const nameInp   = mk('AUTHORIZATION', rule.name, false);
      const prefixInp = mk('Bearer ', rule.prefix, false);

      const del = document.createElement('button');
      del.type = 'button';
      del.style.cssText = 'background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;padding:0;line-height:1;';
      del.textContent = '×';
      del.onclick = () => row.remove();

      row.appendChild(pathInp);
      row.appendChild(nameInp);
      row.appendChild(prefixInp);
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
        const [pathInp, nameInp, prefixInp] = row.querySelectorAll('input');
        const path = pathInp?.value.trim();
        const name = nameInp?.value.trim();
        if (path && name) rows.push({ path, name, prefix: prefixInp?.value || '' });
      });
      return rows;
    };

    return div;
  }

  const preScriptSection = makeScriptSection(
    r.pre_lang, r.pre_script,
    'Runs before the request. Use qc.set("var", value) to inject variables into URL/headers/body.'
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

  // ── Send ──
  sendBtn.onclick = async () => {
    let rid = requestId;
    if (!rid) {
      const saved = await _save();
      if (!saved) return;
      rid = saved;
    }
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending…';
    try {
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
