/**
 * renderCollectionsView(container, onSelectRequest)
 * container: DOM element to render into
 * onSelectRequest: (requestId) => void
 */
export function renderCollectionsView(container, onSelectRequest) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading...</div>';

  let _envNames = [];

  async function _loadEnvNames() {
    try {
      const res = await window.api('GET', '/envs');
      const envs = res.environments || res.envs || [];
      _envNames = envs.map(e => (typeof e === 'string' ? e : (e.name || '')));
    } catch(e) { _envNames = []; }
  }

  async function reload() {
    await _loadEnvNames();
    const res = await window.api('GET', '/collections');
    const collections = res.collections || [];
    container.innerHTML = '';

    if (!collections.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted text-sm';
      empty.style.cssText = 'padding:10px 14px;';
      empty.textContent = 'No collections yet.';
      container.appendChild(empty);
      const newColBtn = document.createElement('div');
      newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
      newColBtn.textContent = '+ New Collection';
      newColBtn.onclick = _createCollection;
      container.appendChild(newColBtn);
      return;
    }

    collections.forEach(col => {
      const section = document.createElement('div');
      section.className = 'api-collection-section';

      // Collection header row
      const header = document.createElement('div');
      header.className = 'api-collection-item';

      const leftSide = document.createElement('span');
      leftSide.innerHTML = `<strong>${_esc(col.name)}</strong> <span class="text-muted text-sm">(${col.request_count})</span>`;
      header.appendChild(leftSide);

      const rightSide = document.createElement('span');
      rightSide.style.display = 'flex';
      rightSide.style.gap = '4px';
      rightSide.style.alignItems = 'center';

      // Env selector
      const envSel = document.createElement('select');
      envSel.title = 'Environment for this collection';
      envSel.style.cssText = 'font-size:11px;padding:2px 4px;border:1px solid var(--border);border-radius:4px;background:var(--surface-1);color:var(--text-muted);max-width:90px;';
      envSel.innerHTML = '<option value="">No env</option>';
      _envNames.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        if (name === col.env_name) opt.selected = true;
        envSel.appendChild(opt);
      });
      envSel.addEventListener('change', async (e) => {
        e.stopPropagation();
        col.env_name = envSel.value || null;
        await window.api('PATCH', `/collections/${col.id}`, { env_name: col.env_name });
      });
      rightSide.appendChild(envSel);

      // Collection vars toggle
      let varsExpanded = false;
      const varsBtn = document.createElement('button');
      varsBtn.className = 'btn btn-xs btn-ghost';
      varsBtn.textContent = 'Vars';
      varsBtn.title = 'Collection variables — seed values for {{VAR}} set by post-scripts';
      rightSide.appendChild(varsBtn);

      const runBtn = document.createElement('button');
      runBtn.className = 'btn btn-xs btn-ghost';
      runBtn.textContent = '▶ Run';
      runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name, col.env_name); };
      rightSide.appendChild(runBtn);

      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-xs btn-ghost';
      delBtn.style.color = 'var(--danger, #e53e3e)';
      delBtn.textContent = '✕';
      delBtn.title = 'Delete collection';
      delBtn.onclick = (e) => { e.stopPropagation(); _deleteCollection(col.id, col.name); };
      rightSide.appendChild(delBtn);

      const expandBtn = document.createElement('button');
      expandBtn.className = 'btn btn-xs btn-ghost';
      expandBtn.textContent = '▾';
      rightSide.appendChild(expandBtn);
      header.appendChild(rightSide);

      section.appendChild(header);

      // Requests list (togglable)
      const reqList = document.createElement('div');
      reqList.className = 'api-requests-list';
      let expanded = true;

      function _toggleExpand() {
        expanded = !expanded;
        reqList.style.display = expanded ? '' : 'none';
        expandBtn.textContent = expanded ? '▾' : '▸';
      }
      header.onclick = (e) => {
        if (e.target === runBtn || e.target === expandBtn || e.target === varsBtn || e.target === envSel) return;
        _toggleExpand();
      };
      expandBtn.onclick = (e) => { e.stopPropagation(); _toggleExpand(); };

      // ── Collection Vars Panel ──
      const varsPanel = document.createElement('div');
      varsPanel.style.cssText = 'display:none;padding:8px 14px 6px;border-bottom:1px solid var(--border);';

      const varsPanelHdr = document.createElement('div');
      varsPanelHdr.style.cssText = 'font-size:10px;color:var(--text-muted);margin-bottom:6px;line-height:1.4;';
      varsPanelHdr.textContent = 'Seed values for {{VAR}} tokens set by post-scripts (qc.set). Pre-populated before each run.';
      varsPanel.appendChild(varsPanelHdr);

      const varsTableEl = document.createElement('table');
      varsTableEl.style.cssText = 'width:100%;font-size:11px;border-collapse:collapse;';
      varsTableEl.innerHTML = '<thead><tr><th style="text-align:left;padding:0 4px 3px;color:var(--text-muted);font-weight:500;">Variable</th><th style="text-align:left;padding:0 4px 3px;color:var(--text-muted);font-weight:500;">Initial value</th><th style="width:24px"></th></tr></thead>';
      const varsTbody = document.createElement('tbody');
      varsTableEl.appendChild(varsTbody);
      varsPanel.appendChild(varsTableEl);

      const addVarBtn = document.createElement('button');
      addVarBtn.type = 'button';
      addVarBtn.className = 'btn btn-xs btn-ghost';
      addVarBtn.style.marginTop = '4px';
      addVarBtn.textContent = '+ Add Variable';
      varsPanel.appendChild(addVarBtn);

      function _addVarRow(v = { key: '', initial_value: '' }) {
        const tr = document.createElement('tr');
        const keyTd = document.createElement('td');
        keyTd.style.padding = '2px 4px';
        const keyInp = document.createElement('input');
        keyInp.type = 'text'; keyInp.placeholder = 'var_name';
        keyInp.value = v.key || '';
        keyInp.className = 'input-sm';
        keyInp.style.cssText = 'font-family:var(--font-mono);font-size:11px;width:100%;';
        keyTd.appendChild(keyInp);

        const valTd = document.createElement('td');
        valTd.style.padding = '2px 4px';
        const valInp = document.createElement('input');
        valInp.type = 'text'; valInp.placeholder = '(empty — set by post-script)';
        valInp.value = v.initial_value || '';
        valInp.className = 'input-sm';
        valInp.style.cssText = 'font-size:11px;width:100%;';
        valTd.appendChild(valInp);

        const delTd = document.createElement('td');
        delTd.style.padding = '2px 0';
        const delBtn = document.createElement('button');
        delBtn.type = 'button'; delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
        delBtn.textContent = '×';
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
      }

      addVarBtn.onclick = (e) => { e.stopPropagation(); _addVarRow(); };

      let _colVarsLoaded = false;
      async function _toggleVarsPanel() {
        varsExpanded = !varsExpanded;
        varsPanel.style.display = varsExpanded ? '' : 'none';
        varsBtn.classList.toggle('active', varsExpanded);
        if (varsExpanded && !_colVarsLoaded) {
          _colVarsLoaded = true;
          const res = await window.api('GET', `/collections/${col.id}/vars`);
          (res.vars || []).forEach(v => _addVarRow(v));
        }
      }
      varsBtn.onclick = (e) => { e.stopPropagation(); _toggleVarsPanel(); };

      section.appendChild(varsPanel);

      // Load requests for this collection
      window.api('GET', `/api-requests?collection_id=${col.id}`).then(r => {
        const reqs = r.requests || [];
        reqs.forEach(req => {
          const item = document.createElement('div');
          item.className = 'api-request-item';
          item.dataset.requestId = req.id;
          const methodClass = `method-${req.method}`;
          item.innerHTML = `<span class="method-badge ${methodClass}">${_esc(req.method)}</span> <span>${_esc(req.name)}</span>`;
          item.onclick = () => {
            container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            onSelectRequest(req.id, null, col.id, col.env_name);
          };
          reqList.appendChild(item);
        });

        // "New request in collection" button
        const newReqBtn = document.createElement('div');
        newReqBtn.className = 'api-request-item';
        newReqBtn.innerHTML = `<span style="color:var(--text-muted)">+ New Request</span>`;
        newReqBtn.onclick = () => {
          container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
          newReqBtn.classList.add('active');
          onSelectRequest(null, col.id, col.id, col.env_name);
        };
        reqList.appendChild(newReqBtn);
      });

      section.appendChild(reqList);
      container.appendChild(section);
    });

    // "New collection" at bottom
    const newColBtn = document.createElement('div');
    newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
    newColBtn.textContent = '+ New Collection';
    newColBtn.onclick = _createCollection;
    container.appendChild(newColBtn);
  }

  async function _runCollection(colId, colName, envName) {
    const confirmed = await window._confirmDialog(`Run '${colName}'?`, 'All requests in this collection will be executed in order.', 'Run');
    if (!confirmed) return;
    const res = await window.api('POST', `/collections/${colId}/run`, { env_name: envName || null });
    if (res.ok === false) {
      await window._alertDialog('Run failed: ' + res.error);
    } else {
      window._toast(`Run complete: ${res.passed}/${res.total} passed`);
    }
  }

  async function _deleteCollection(colId, colName) {
    const confirmed = await window._confirmDialog(`Delete '${colName}'?`, 'All requests in this collection will be permanently deleted.', 'Delete', 'btn btn-sm btn-danger');
    if (!confirmed) return;
    const res = await window.api('DELETE', `/collections/${colId}`);
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  async function _createCollection() {
    const name = await window._promptDialog('Collection name:');
    if (!name) return;
    const res = await window.api('POST', '/collections', { name: name.trim() });
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  reload();
}
