import { createInlineVarDrop } from '../components/inline-var-drop.js';
import { attachTokenOverlay } from '../components/var-token-overlay.js';
import { applyVarStyle } from '../components/var-style.js';
import { createEnvSelector } from '../components/env-selector.js';
import { onEnvChanged } from '../components/env-events.js';

/**
 * renderCollectionSettingsTabs(host, col) → { destroy }
 *
 * Builds the collection's Auth / Variables / Schema Check / Negative tab UI into
 * `host`. Extracted so it can be reused verbatim by both the collection-detail
 * page and the collection-settings drawer opened from the request editor —
 * one implementation of each settings surface, no drift.
 *
 * The tabs read/write the collection via the same endpoints as before and keep
 * their var styling in sync with the shared env-changed signal.
 */
export function renderCollectionSettingsTabs(host, col) {
  // Env (col.env_name) + Collection vars — feeds the {{ }} suggestion dropdown
  // and existence-based coloring on the Auth tab fields.
  let _knownVarNames = null;
  let _allVarsList = null;
  let _authFieldInputs = [];
  let _authFieldOverlays = [];
  let _varSuggestUIs = [];
  // Set when the Variables tab is built, so the controller can add+focus a row.
  let _varsAddRow = null;

  async function getAllVars() {
    const results = [];
    if (col.env_name) {
      try {
        const res = await window.api('GET', `/envs/${encodeURIComponent(col.env_name)}`);
        (res.variables || []).forEach(v => results.push({ key: v.key, value: v.value, is_secret: !!v.is_secret, group: 'Environment' }));
      } catch(e) { /* no env */ }
    }
    try {
      const res = await window.api('GET', `/collections/${col.id}/vars`);
      (res.vars || []).forEach(v => results.push({ key: v.key, value: v.initial_value || '', is_secret: !!v.is_secret, group: 'Collection' }));
    } catch(e) { /* no collection vars */ }
    return results;
  }

  async function _refreshKnownVarNames() {
    const vars = await getAllVars();
    _knownVarNames = new Set(vars.map(v => v.key));
    _allVarsList = vars;
    _authFieldInputs.forEach(inp => applyVarStyle(inp, _knownVarNames));
    _authFieldOverlays.forEach(o => o.refresh());
    _varSuggestUIs.forEach(u => u.invalidate());
  }

  // ── Auth tab ──
  function _buildAuthTab(wrap) {
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:16px;';

    // Auth type row
    const typeRow = document.createElement('div');
    typeRow.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
    const typeLbl = document.createElement('label');
    typeLbl.style.cssText = 'font-size:11px;font-weight:500;color:var(--text-secondary);letter-spacing:.04em;text-transform:uppercase;';
    typeLbl.textContent = 'Auth Type';
    const authTypeSel = document.createElement('select');
    authTypeSel.className = 'input-sm';
    authTypeSel.style.cssText = 'font-size:13px;width:100%;max-width:240px;';
    const COL_AUTH_LABELS = { none: 'No Auth', bearer: 'Bearer Token', basic: 'Basic Auth', api_key: 'API Key', oauth2: 'OAuth 2 / Custom' };
    Object.entries(COL_AUTH_LABELS).forEach(([val, label]) => {
      const opt = document.createElement('option');
      opt.value = val; opt.textContent = label;
      if ((col.auth_type || 'none') === val) opt.selected = true;
      authTypeSel.appendChild(opt);
    });
    typeRow.appendChild(typeLbl);
    typeRow.appendChild(authTypeSel);
    wrap.appendChild(typeRow);

    const authFieldsWrap = document.createElement('div');
    authFieldsWrap.style.cssText = 'display:flex;flex-direction:column;gap:12px;';
    wrap.appendChild(authFieldsWrap);

    let _colAuthConfig = {};
    try { _colAuthConfig = JSON.parse(col.auth_config || '{}'); } catch(e) { _colAuthConfig = {}; }

    const _authInlineDrop = createInlineVarDrop(getAllVars);
    _varSuggestUIs.push(_authInlineDrop);

    function _colAuthField(label, placeholder, key) {
      const fw = document.createElement('div');
      fw.style.cssText = 'display:flex;flex-direction:column;gap:5px;';
      const lbl = document.createElement('label');
      lbl.style.cssText = 'font-size:11px;font-weight:500;color:var(--text-secondary);letter-spacing:.04em;text-transform:uppercase;';
      lbl.textContent = label;
      const inp = document.createElement('input');
      inp.type = /password|secret/i.test(label) ? 'password' : 'text';
      inp.className = 'input-sm';
      inp.style.cssText = 'font-size:13px;width:100%;font-family:var(--font-mono);';
      inp.placeholder = placeholder;
      inp.value = _colAuthConfig[key] || '';
      inp.addEventListener('input', () => applyVarStyle(inp, _knownVarNames));
      inp.addEventListener('blur', async () => {
        _colAuthConfig[key] = inp.value;
        col.auth_config = JSON.stringify(_colAuthConfig);
        await window.api('PATCH', `/collections/${col.id}`, { auth_type: authTypeSel.value, auth_config: col.auth_config });
      });
      applyVarStyle(inp, _knownVarNames);
      _authInlineDrop.watchInput(inp);
      _authFieldInputs.push(inp);
      const overlay = attachTokenOverlay(inp, () => _allVarsList);
      _authFieldOverlays.push(overlay);
      fw.appendChild(lbl);
      fw.appendChild(overlay.el);
      return fw;
    }

    function _renderColAuthFields(type) {
      _authInlineDrop.close();
      authFieldsWrap.innerHTML = '';
      _authFieldInputs = [];
      _authFieldOverlays = [];
      if (type === 'none') {
        const hint = document.createElement('div');
        hint.style.cssText = 'font-size:12px;color:var(--text-muted);padding:10px 14px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);';
        hint.textContent = 'No authentication — inheriting requests will send no auth headers.';
        authFieldsWrap.appendChild(hint);
      } else if (type === 'bearer') {
        authFieldsWrap.appendChild(_colAuthField('Bearer Token', '{{access_token}}', 'token'));
      } else if (type === 'basic') {
        authFieldsWrap.appendChild(_colAuthField('Username', '{{username}}', 'username'));
        authFieldsWrap.appendChild(_colAuthField('Password', '{{password}}', 'password'));
      } else if (type === 'api_key') {
        authFieldsWrap.appendChild(_colAuthField('Header / Param Name', 'X-API-Key', 'key'));
        authFieldsWrap.appendChild(_colAuthField('Key Value', '{{api_key}}', 'value'));
      } else if (type === 'oauth2') {
        authFieldsWrap.appendChild(_colAuthField('Token URL', 'https://...', 'token_url'));
        authFieldsWrap.appendChild(_colAuthField('Client ID', '{{client_id}}', 'client_id'));
        authFieldsWrap.appendChild(_colAuthField('Client Secret', '{{client_secret}}', 'client_secret'));
      }
    }

    authTypeSel.addEventListener('change', async () => {
      col.auth_type = authTypeSel.value;
      _renderColAuthFields(authTypeSel.value);
      // Don't send auth_config here — omitting it lets the PATCH route keep
      // the stored value (routes/collections.py falls back to col.auth_config
      // when the key is absent). Sending '{}' wiped a saved token just from
      // clicking through the dropdown, with no field ever touched.
      await window.api('PATCH', `/collections/${col.id}`, { auth_type: col.auth_type });
    });

    _renderColAuthFields(col.auth_type || 'none');
    _refreshKnownVarNames();

    // Divider + bulk action
    const divider = document.createElement('div');
    divider.style.cssText = 'height:1px;background:var(--border-subtle);margin-top:4px;';
    wrap.appendChild(divider);

    const bulkInheritBtn = document.createElement('button');
    bulkInheritBtn.type = 'button';
    bulkInheritBtn.className = 'btn btn-xs btn-ghost';
    bulkInheritBtn.style.cssText = 'align-self:flex-start;font-size:11px;color:var(--text-secondary);';
    bulkInheritBtn.textContent = 'Set all requests → Inherit auth';
    bulkInheritBtn.title = 'Switch every request in this collection to "Inherit from Collection" auth';
    bulkInheritBtn.onclick = async () => {
      bulkInheritBtn.disabled = true;
      bulkInheritBtn.textContent = 'Updating…';
      const res = await window.api('GET', `/api-requests?collection_id=${col.id}`);
      const reqs = res.requests || [];
      await Promise.all(reqs.map(req =>
        window.api('PATCH', `/api-requests/${req.id}`, { auth_type: 'inherit', auth_config: '{}' })
      ));
      bulkInheritBtn.textContent = `✓ Done — ${reqs.length} updated`;
      setTimeout(() => { bulkInheritBtn.disabled = false; bulkInheritBtn.textContent = 'Set all requests → Inherit auth'; }, 2500);
    };
    wrap.appendChild(bulkInheritBtn);
  }

  // ── Variables tab ──
  function _buildVarsTab(wrap) {
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:12px;';

    const hdr = document.createElement('div');
    hdr.style.cssText = 'font-size:12px;color:var(--text-secondary);line-height:1.5;';
    hdr.textContent = 'Seed values for {{var}} tokens set by post-scripts (qc.set). Pre-populated before each run. Tick Secret to encrypt a value at rest.';
    wrap.appendChild(hdr);

    const tableWrap = document.createElement('div');
    tableWrap.style.cssText = 'border:1px solid var(--border-default);border-radius:var(--radius-sm);overflow:hidden;';

    const varsTableEl = document.createElement('table');
    varsTableEl.style.cssText = 'width:100%;font-size:12px;border-collapse:collapse;';
    varsTableEl.innerHTML = `<thead><tr style="background:var(--bg-elevated);">
      <th style="text-align:left;padding:7px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Variable</th>
      <th style="text-align:left;padding:7px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Initial value</th>
      <th style="width:56px;text-align:center;padding:7px 4px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Secret</th>
      <th style="width:32px;border-bottom:1px solid var(--border-default);"></th>
    </tr></thead>`;
    const varsTbody = document.createElement('tbody');
    varsTableEl.appendChild(varsTbody);
    tableWrap.appendChild(varsTableEl);
    wrap.appendChild(tableWrap);

    const addVarBtn = document.createElement('button');
    addVarBtn.type = 'button';
    addVarBtn.className = 'btn btn-xs btn-ghost';
    addVarBtn.style.cssText = 'align-self:flex-start;font-size:11px;';
    addVarBtn.textContent = '+ Add Variable';
    wrap.appendChild(addVarBtn);

    function _addVarRow(v = { key: '', initial_value: '', is_secret: 0 }, isNew = false) {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-subtle)';
      const isSecretInitially = !!v.is_secret;
      if (isSecretInitially) tr.dataset.masked = '1';

      const keyTd = document.createElement('td');
      keyTd.style.padding = '4px 6px';
      const keyInp = document.createElement('input');
      keyInp.type = 'text'; keyInp.placeholder = 'variable_name';
      keyInp.value = v.key || '';
      keyInp.className = 'input-sm';
      keyInp.style.cssText = 'font-family:var(--font-mono);font-size:11px;width:100%;background:transparent;border-color:transparent;';
      keyInp.addEventListener('focus', () => { keyInp.style.borderColor = ''; });
      keyInp.addEventListener('blur',  () => { keyInp.style.borderColor = 'transparent'; });
      keyTd.appendChild(keyInp);

      const valTd = document.createElement('td');
      valTd.style.padding = '4px 6px';
      const valInp = document.createElement('input');
      valInp.type = isSecretInitially ? 'password' : 'text';
      valInp.placeholder = '(empty — set by post-script)';
      valInp.value = v.initial_value || '';
      valInp.className = 'input-sm';
      valInp.style.cssText = 'font-size:12px;width:100%;background:transparent;border-color:transparent;';
      valInp.addEventListener('focus', () => {
        valInp.style.borderColor = '';
        if (tr.dataset.masked === '1' && !tr.dataset.edited) valInp.value = '';
      });
      valInp.addEventListener('input', () => { tr.dataset.edited = '1'; delete tr.dataset.masked; });
      valInp.addEventListener('blur',  () => { valInp.style.borderColor = 'transparent'; });
      valTd.appendChild(valInp);

      const secretTd = document.createElement('td');
      secretTd.style.cssText = 'padding:4px 6px;text-align:center;';
      const secretCb = document.createElement('input');
      secretCb.type = 'checkbox';
      secretCb.checked = isSecretInitially;
      secretCb.title = 'Secret';
      secretTd.appendChild(secretCb);

      const delTd = document.createElement('td');
      delTd.style.cssText = 'padding:4px 6px;text-align:center;';
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.style.cssText = 'background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px;padding:0 4px;line-height:1;opacity:.6;';
      delBtn.textContent = '×';
      delBtn.onmouseenter = () => { delBtn.style.color = 'var(--danger)'; delBtn.style.opacity = '1'; };
      delBtn.onmouseleave = () => { delBtn.style.color = 'var(--text-muted)'; delBtn.style.opacity = '.6'; };
      delTd.appendChild(delBtn);

      async function _saveRow() {
        const key = keyInp.value.trim();
        if (!key) return;
        const is_secret = secretCb.checked ? 1 : 0;
        if (is_secret && tr.dataset.masked === '1') {
          await window.api('PUT', `/collections/${col.id}/vars/${encodeURIComponent(key)}`, { is_secret, unchanged: true });
        } else {
          await window.api('PUT', `/collections/${col.id}/vars/${encodeURIComponent(key)}`, { initial_value: valInp.value, is_secret });
        }
        _refreshKnownVarNames();
      }
      async function _deleteRow() {
        const key = keyInp.value.trim();
        if (key) await window.api('DELETE', `/collections/${col.id}/vars/${encodeURIComponent(key)}`);
        tr.remove();
        _refreshKnownVarNames();
      }
      async function _onSecretToggle() {
        // Un-ticking a stored-masked secret: fetch decrypted value so the user sees it,
        // but only if the row is still masked (user hasn't already typed a replacement).
        if (!secretCb.checked && tr.dataset.masked === '1') {
          const key = keyInp.value.trim();
          if (key) {
            try {
              const res = await window.api('GET', `/collections/${col.id}/vars/${encodeURIComponent(key)}/reveal`);
              if (res && res.ok) valInp.value = res.value || '';
            } catch (e) { /* reveal failed, leave placeholder as-is */ }
          }
        }
        valInp.type = secretCb.checked ? 'password' : 'text';
        delete tr.dataset.masked;
        tr.dataset.edited = '1';
        await _saveRow();
      }

      keyInp.addEventListener('blur', _saveRow);
      valInp.addEventListener('blur', _saveRow);
      secretCb.addEventListener('change', _onSecretToggle);
      delBtn.onclick = _deleteRow;

      tr.appendChild(keyTd); tr.appendChild(valTd); tr.appendChild(secretTd); tr.appendChild(delTd);
      varsTbody.appendChild(tr);
      if (isNew) keyInp.focus();
    }

    addVarBtn.onclick = () => _addVarRow({ key: '', initial_value: '', is_secret: 0 }, true);
    _varsAddRow = _addVarRow; // expose to the tabs controller (drawer add-variable)

    window.api('GET', `/collections/${col.id}/vars`).then(res => {
      (res.vars || []).forEach(v => _addVarRow(v));
    });
  }

  // ── Schema Check tab ──
  function _buildSchemaTab(wrap) {
    wrap.className = 'sc-panel';
    wrap.style.cssText = '';
    wrap.innerHTML = `
      <p class="sc-desc">Default for every request in this collection.
        Changing it <strong>resets all per-request overrides</strong> so each request follows this setting —
        you can override an individual request afterward.</p>
      <div class="sc-row">
        <div class="sc-row__label">Default for all requests</div>
        <div class="sc-row__body">
          <div class="sc-seg" role="group" aria-label="Collection schema-check default">
            <button type="button" class="sc-seg__btn" data-val="on">On</button>
            <button type="button" class="sc-seg__btn" data-val="off">Off</button>
          </div>
          <div class="sc-row__hint">On — every request is checked. Off — none are, unless a request is individually turned on.</div>
        </div>
      </div>`;

    const seg = wrap.querySelector('.sc-seg');
    function paint() {
      const cur = col.schema_check_default || 'off';
      seg.querySelectorAll('.sc-seg__btn').forEach(b =>
        b.classList.toggle('is-active', b.dataset.val === cur));
    }
    seg.querySelectorAll('.sc-seg__btn').forEach(b => {
      b.onclick = async () => {
        const val = b.dataset.val;
        if ((col.schema_check_default || 'off') === val) return;
        const msg = `Turn schema check ${val === 'on' ? 'On' : 'Off'} for every request in “${col.name}”? `
          + 'This resets all per-request overrides.';
        const ok = await (window._confirmDialog
          ? window._confirmDialog(msg)
          : Promise.resolve(window.confirm(msg)));
        if (!ok) return;
        col.schema_check_default = val;
        paint();
        await window.api('PATCH', `/collections/${col.id}`, { schema_check_default: val });
      };
    });
    paint();
  }

  // ── Negative testing tab ──
  function _buildNegativeTab(wrap) {
    wrap.className = 'sc-panel';
    wrap.style.cssText = '';
    wrap.innerHTML = `
      <p class="sc-desc">Negative-testing default for every request in this collection.
        Changing it <strong>resets all per-request overrides</strong> so each request follows this setting —
        you can override an individual request afterward.</p>
      <div class="sc-row">
        <div class="sc-row__label">Default for all requests</div>
        <div class="sc-row__body">
          <div class="sc-seg" role="group" aria-label="Collection negative-testing default">
            <button type="button" class="sc-seg__btn" data-val="on">On</button>
            <button type="button" class="sc-seg__btn" data-val="off">Off</button>
          </div>
          <div class="sc-row__hint">On — negatives run for every request in collection runs. Off — none, unless a request is individually turned on.</div>
        </div>
      </div>`;

    const seg = wrap.querySelector('.sc-seg');
    function paint() {
      const cur = col.negative_check_default || 'off';
      seg.querySelectorAll('.sc-seg__btn').forEach(b =>
        b.classList.toggle('is-active', b.dataset.val === cur));
    }
    seg.querySelectorAll('.sc-seg__btn').forEach(b => {
      b.onclick = async () => {
        const val = b.dataset.val;
        if ((col.negative_check_default || 'off') === val) return;
        const msg = `Turn negative testing ${val === 'on' ? 'On' : 'Off'} for every request in “${col.name}”? `
          + 'This resets all per-request overrides.';
        const ok = await (window._confirmDialog
          ? window._confirmDialog(msg)
          : Promise.resolve(window.confirm(msg)));
        if (!ok) return;
        col.negative_check_default = val;
        paint();
        await window.api('PATCH', `/collections/${col.id}`, { negative_check_default: val });
      };
    });
    paint();
  }

  // Tabs
  host.innerHTML = '';
  const tabsEl = document.createElement('div');
  tabsEl.style.cssText = 'display:flex;gap:0;border-bottom:1px solid var(--border-default);margin-bottom:20px;';
  const contentEl = document.createElement('div');
  host.appendChild(tabsEl);
  host.appendChild(contentEl);

  const TABS = [
    { id: 'auth', label: 'Auth', build: _buildAuthTab },
    { id: 'vars', label: 'Variables', build: _buildVarsTab },
    { id: 'schema', label: 'Schema Check', build: _buildSchemaTab },
    { id: 'negative', label: 'Negative', build: _buildNegativeTab },
  ];

  let _activeTab = null;
  const _panels = {};
  const _btns = {};

  TABS.forEach(tab => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.style.cssText = 'background:none;border:none;border-bottom:2px solid transparent;padding:8px 16px;font-size:12px;font-weight:500;cursor:pointer;color:var(--text-muted);margin-bottom:-1px;letter-spacing:.01em;transition:color .15s;';
    btn.textContent = tab.label;
    btn.onmouseenter = () => { if (_activeTab !== tab.id) btn.style.color = 'var(--text-secondary)'; };
    btn.onmouseleave = () => { if (_activeTab !== tab.id) btn.style.color = 'var(--text-muted)'; };
    tabsEl.appendChild(btn);
    _btns[tab.id] = btn;

    const panel = document.createElement('div');
    panel.style.display = 'none';
    contentEl.appendChild(panel);
    _panels[tab.id] = { el: panel, built: false };

    btn.onclick = () => _switchTab(tab.id);
  });

  function _switchTab(id) {
    if (_activeTab) {
      _panels[_activeTab].el.style.display = 'none';
      _btns[_activeTab].style.color = 'var(--text-muted)';
      _btns[_activeTab].style.borderBottomColor = 'transparent';
      _btns[_activeTab].style.fontWeight = '500';
    }
    _activeTab = id;
    const panel = _panels[id];
    if (!panel.built) {
      panel.built = true;
      TABS.find(t => t.id === id).build(panel.el);
    }
    panel.el.style.display = '';
    _btns[id].style.color = 'var(--accent)';
    _btns[id].style.borderBottomColor = 'var(--accent)';
    _btns[id].style.fontWeight = '600';
  }

  _switchTab('auth');

  // Keep the tabs' var styling consistent when the environment binding changes
  // elsewhere (the header selector, or the request editor's selector/drawer).
  const _unsub = onEnvChanged(({ collectionId, envName }) => {
    if (String(collectionId) !== String(col.id)) return;
    col.env_name = envName;
    _refreshKnownVarNames();
  });

  return {
    openTab(id) { _switchTab(id); },
    addVariable() {
      _switchTab('vars');
      if (_varsAddRow) _varsAddRow({ key: '', initial_value: '', is_secret: 0 }, true);
    },
    destroy() { try { _unsub(); } catch (_) {} },
  };
}

/**
 * renderCollectionDetailView(container, col, runId, onViewRun, onBack)
 *
 * The collection-detail page: header (back / title / env selector / run), the
 * run-status card, and the settings tabs (delegated to renderCollectionSettingsTabs).
 */
export function renderCollectionDetailView(container, col, runId, onViewRun, onBack) {
  let _pollTimer = null;
  let _destroyed = false;
  let _tabsCtl = null;
  let _envSelector = null;

  function _destroy() {
    _destroyed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_tabsCtl) { _tabsCtl.destroy(); _tabsCtl = null; }
    if (_envSelector) { try { _envSelector.destroy(); } catch (_) {} _envSelector = null; }
    if (container.__cdvEnvUnsub) { try { container.__cdvEnvUnsub(); } catch (_) {} container.__cdvEnvUnsub = null; }
  }
  container.__destroyRunView = _destroy;

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _renderCard(run) {
    const el = document.getElementById('cdv-card');
    if (!el) return;
    if (!run) { el.style.display = 'none'; return; }

    const isRunning   = run.status === 'RUNNING';
    const done        = (run.request_results || []).length;
    const total       = run.total || 0;
    const pct         = total > 0 ? Math.round(done / total * 100) : 0;
    const statusColor = isRunning         ? 'var(--warning,#f59e0b)'
      : run.status === 'PASSED'           ? 'var(--success,#10b981)'
      :                                     'var(--danger,#ef4444)';

    el.style.display = '';
    el.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
        <span style="font-size:12px;font-weight:600;color:${statusColor};display:flex;align-items:center;gap:6px;">
          ${isRunning ? '<span style="animation:cdv-pulse 1s infinite;display:inline-block;">⟳</span>' : ''}
          ${_esc(run.status)} &nbsp;·&nbsp; ${done}/${total} &nbsp;·&nbsp; ${run.passed} passed &nbsp;·&nbsp; ${run.failed} failed
        </span>
        <div style="display:flex;gap:6px;">
          ${isRunning ? `<button class="btn btn-xs btn-danger" id="cdv-stop">■ Stop</button>` : ''}
          <button class="btn btn-xs btn-ghost" id="cdv-view">View Progress →</button>
        </div>
      </div>
      <div style="height:3px;background:var(--border-default);border-radius:2px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:${statusColor};border-radius:2px;transition:width .4s;"></div>
      </div>`;

    const viewBtn = document.getElementById('cdv-view');
    if (viewBtn) viewBtn.onclick = () => { _destroy(); if (onViewRun) onViewRun(run.id); };

    const stopBtn = document.getElementById('cdv-stop');
    if (stopBtn) stopBtn.onclick = async () => {
      stopBtn.disabled = true; stopBtn.textContent = 'Stopping…';
      await window.api('POST', `/api-collection-runs/${run.id}/stop`);
    };

    if (!isRunning) {
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    }
  }

  async function _poll() {
    if (_destroyed || !runId) return;
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (res.ok && res.run) _renderCard(res.run);
    } catch (_) {}
  }

  async function _init() {
    container.innerHTML = `
      <style>
        @keyframes cdv-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
      </style>
      <div style="padding:24px 28px;max-width:660px;">

        <!-- Header -->
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px;">
          <button class="btn btn-xs btn-ghost" id="cdv-back" style="flex-shrink:0;">← Back</button>
          <div style="flex:1;min-width:0;">
            <div style="font-size:16px;font-weight:700;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(col.name)}</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${col.request_count || 0} requests</div>
          </div>
          <span id="cdv-env-slot" style="flex-shrink:0;display:inline-flex;"></span>
          <button class="btn btn-sm btn-primary" id="cdv-run" style="flex-shrink:0;white-space:nowrap;">▶ Run</button>
        </div>

        <!-- Run status card -->
        <div id="cdv-card" style="display:none;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-md);padding:12px 16px;margin-bottom:20px;"></div>

        <!-- Settings tabs -->
        <div id="cdv-settings-host"></div>

      </div>`;

    document.getElementById('cdv-back').onclick = () => { _destroy(); if (onBack) onBack(); };

    // Run button in header
    document.getElementById('cdv-run').onclick = async () => {
      const { run, mode, confirm_destructive } = await window.qcCollectionRunConfirm(col.id, col.name, col.env_name);
      if (!run) return;
      const runBtn = document.getElementById('cdv-run');
      if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Running…'; }
      const res = await window.api('POST', `/collections/${col.id}/run`, { env_name: col.env_name || null, confirm_destructive, negatives_mode: mode });
      if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = '▶&nbsp; Run'; }
      if (res.ok === false) { await window._alertDialog('Run failed: ' + res.error); return; }
      if (onViewRun && res.run_id) onViewRun(res.run_id);
    };

    // Env selector (shared component) — binds env to the collection and emits
    // the env-changed signal so the request editor / drawer stay in sync.
    _envSelector = createEnvSelector({
      collectionId: col.id,
      envName: col.env_name,
      onChange: (name) => { col.env_name = name; },
    });
    document.getElementById('cdv-env-slot').appendChild(_envSelector.el);

    container.__cdvEnvUnsub = onEnvChanged(({ collectionId, envName }) => {
      if (String(collectionId) !== String(col.id)) return;
      col.env_name = envName;
      _envSelector.setEnv(envName);
    });

    // Settings tabs
    _tabsCtl = renderCollectionSettingsTabs(document.getElementById('cdv-settings-host'), col);

    if (runId) {
      await _poll();
      _pollTimer = setInterval(_poll, 2000);
    }
  }

  _init();
}
