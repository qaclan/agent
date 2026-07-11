/**
 * renderCollectionDetailView(container, col, runId, onViewRun, onBack)
 * Shows collection detail with Environment selector, Auth + Variables tabs.
 * If runId provided, shows a live run summary card.
 * Polls GET /api/api-collection-runs/<runId> every 2s while RUNNING.
 * Sets container.__destroyRunView for teardown by parent.
 */
export function renderCollectionDetailView(container, col, runId, onViewRun, onBack) {
  let _pollTimer = null;
  let _destroyed = false;

  function _destroy() {
    _destroyed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
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
      inp.addEventListener('blur', async () => {
        _colAuthConfig[key] = inp.value;
        col.auth_config = JSON.stringify(_colAuthConfig);
        await window.api('PATCH', `/collections/${col.id}`, { auth_type: authTypeSel.value, auth_config: col.auth_config });
      });
      fw.appendChild(lbl);
      fw.appendChild(inp);
      return fw;
    }

    function _renderColAuthFields(type) {
      authFieldsWrap.innerHTML = '';
      if (type === 'none') {
        const hint = document.createElement('div');
        hint.style.cssText = 'font-size:12px;color:var(--text-muted);padding:10px 14px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);';
        hint.textContent = 'No authentication — inheriting requests will send no auth headers.';
        authFieldsWrap.appendChild(hint);
      } else if (type === 'bearer') {
        authFieldsWrap.appendChild(_colAuthField('Bearer Token', '{{ACCESS_TOKEN}}', 'token'));
      } else if (type === 'basic') {
        authFieldsWrap.appendChild(_colAuthField('Username', '{{USERNAME}}', 'username'));
        authFieldsWrap.appendChild(_colAuthField('Password', '{{PASSWORD}}', 'password'));
      } else if (type === 'api_key') {
        authFieldsWrap.appendChild(_colAuthField('Header / Param Name', 'X-API-Key', 'key'));
        authFieldsWrap.appendChild(_colAuthField('Key Value', '{{API_KEY}}', 'value'));
      } else if (type === 'oauth2') {
        authFieldsWrap.appendChild(_colAuthField('Token URL', 'https://...', 'token_url'));
        authFieldsWrap.appendChild(_colAuthField('Client ID', '{{CLIENT_ID}}', 'client_id'));
        authFieldsWrap.appendChild(_colAuthField('Client Secret', '{{CLIENT_SECRET}}', 'client_secret'));
      }
    }

    authTypeSel.addEventListener('change', async () => {
      col.auth_type = authTypeSel.value;
      _colAuthConfig = {};
      col.auth_config = '{}';
      _renderColAuthFields(authTypeSel.value);
      await window.api('PATCH', `/collections/${col.id}`, { auth_type: col.auth_type, auth_config: col.auth_config });
    });

    _renderColAuthFields(col.auth_type || 'none');

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
    hdr.textContent = 'Seed values for {{VAR}} tokens set by post-scripts (qc.set). Pre-populated before each run.';
    wrap.appendChild(hdr);

    const tableWrap = document.createElement('div');
    tableWrap.style.cssText = 'border:1px solid var(--border-default);border-radius:var(--radius-sm);overflow:hidden;';

    const varsTableEl = document.createElement('table');
    varsTableEl.style.cssText = 'width:100%;font-size:12px;border-collapse:collapse;';
    varsTableEl.innerHTML = `<thead><tr style="background:var(--bg-elevated);">
      <th style="text-align:left;padding:7px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Variable</th>
      <th style="text-align:left;padding:7px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Initial value</th>
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

    function _addVarRow(v = { key: '', initial_value: '' }, isNew = false) {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-subtle)';

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
      valInp.type = 'text'; valInp.placeholder = '(empty — set by post-script)';
      valInp.value = v.initial_value || '';
      valInp.className = 'input-sm';
      valInp.style.cssText = 'font-size:12px;width:100%;background:transparent;border-color:transparent;';
      valInp.addEventListener('focus', () => { valInp.style.borderColor = ''; });
      valInp.addEventListener('blur',  () => { valInp.style.borderColor = 'transparent'; });
      valTd.appendChild(valInp);

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
        await window.api('PUT', `/collections/${col.id}/vars/${encodeURIComponent(key)}`, { initial_value: valInp.value });
      }
      async function _deleteRow() {
        const key = keyInp.value.trim();
        if (key) await window.api('DELETE', `/collections/${col.id}/vars/${encodeURIComponent(key)}`);
        tr.remove();
      }

      keyInp.addEventListener('blur', _saveRow);
      valInp.addEventListener('blur', _saveRow);
      delBtn.onclick = _deleteRow;

      tr.appendChild(keyTd); tr.appendChild(valTd); tr.appendChild(delTd);
      varsTbody.appendChild(tr);
      if (isNew) keyInp.focus();
    }

    addVarBtn.onclick = () => _addVarRow({ key: '', initial_value: '' }, true);

    window.api('GET', `/collections/${col.id}/vars`).then(res => {
      (res.vars || []).forEach(v => _addVarRow(v));
    });
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
          <select id="cdv-env-sel" class="input-sm" style="flex-shrink:0;max-width:150px;font-size:12px;"></select>
          <button class="btn btn-sm btn-primary" id="cdv-run" style="flex-shrink:0;white-space:nowrap;">▶ Run</button>
        </div>

        <!-- Run status card -->
        <div id="cdv-card" style="display:none;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-md);padding:12px 16px;margin-bottom:20px;"></div>

        <!-- Tabs -->
        <div id="cdv-tabs" style="display:flex;gap:0;border-bottom:1px solid var(--border-default);margin-bottom:20px;"></div>
        <div id="cdv-tab-content"></div>

      </div>`;

    document.getElementById('cdv-back').onclick = () => { _destroy(); if (onBack) onBack(); };

    // Run button in header
    document.getElementById('cdv-run').onclick = async () => {
      const runBtn = document.getElementById('cdv-run');
      if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Running…'; }
      const res = await window.api('POST', `/collections/${col.id}/run`, { env_name: col.env_name || null });
      if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = '▶&nbsp; Run'; }
      if (res.ok === false) { await window._alertDialog('Run failed: ' + res.error); return; }
      if (onViewRun && res.run_id) onViewRun(res.run_id);
    };

    // Env selector
    const envSel = document.getElementById('cdv-env-sel');
    try {
      const envRes = await window.api('GET', '/envs');
      const envNames = (envRes.environments || envRes.envs || []).map(e => typeof e === 'string' ? e : (e.name || ''));
      const noOpt = document.createElement('option');
      noOpt.value = ''; noOpt.textContent = 'No environment';
      envSel.appendChild(noOpt);
      envNames.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        if (name === col.env_name) opt.selected = true;
        envSel.appendChild(opt);
      });
    } catch(_) {}
    envSel.addEventListener('change', async () => {
      col.env_name = envSel.value || null;
      await window.api('PATCH', `/collections/${col.id}`, { env_name: col.env_name });
    });

    // Tabs
    const tabsEl = document.getElementById('cdv-tabs');
    const contentEl = document.getElementById('cdv-tab-content');

    const TABS = [
      { id: 'auth', label: 'Auth', build: _buildAuthTab },
      { id: 'vars', label: 'Variables', build: _buildVarsTab },
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

    if (runId) {
      await _poll();
      _pollTimer = setInterval(_poll, 2000);
    }
  }

  _init();
}
