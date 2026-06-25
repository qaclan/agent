// ── Misc helpers ──────────────────────────────────────────────────────────

function _esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function _mkBtn(label, cls) { const b = document.createElement('button'); b.type='button'; b.className=cls; b.textContent=label; return b; }
function _methodBadgeClass(m) { return `method-badge method-${(m||'GET').toUpperCase()}`; }

const _TYPE_OPTS = ['string','number','integer','boolean','null','array','object'];

// ── Module-level UI builders ──────────────────────────────────────────────

function _showEmptyState(panel) {
  panel.innerHTML = '';
  const el = document.createElement('div');
  el.style.cssText = 'display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;';
  el.innerHTML = '<div style="font-size:28px;opacity:.18;">&#128196;</div><p style="color:var(--text-muted);font-size:13px;margin:0;">Select an endpoint to view its documentation</p>';
  panel.appendChild(el);
}

function _metaChip(label, value) {
  const c = document.createElement('div');
  c.style.cssText = 'display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border-default);border-radius:20px;padding:3px 10px 3px 8px;background:var(--bg-elevated);';
  const l = document.createElement('span');
  l.style.cssText = 'font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted);font-weight:600;';
  l.textContent = label;
  const v = document.createElement('span');
  v.style.cssText = 'font-size:12px;color:var(--text-secondary);font-weight:500;';
  v.textContent = value;
  c.appendChild(l); c.appendChild(v);
  return c;
}

// Mutates rootSchema in-place when type selects change. No API calls.
function _buildSchemaRows(rootSchema, schema, path, depth) {
  const frag = document.createDocumentFragment();
  if (!schema || typeof schema !== 'object') return frag;

  const isArr = Array.isArray(schema);
  const pairs = isArr ? (schema.length ? [['[item]', schema[0]]] : []) : Object.entries(schema);

  pairs.forEach(([rawKey, val], idx) => {
    const pathKey = isArr ? '0' : rawKey;
    const currentPath = path ? `${path}.${pathKey}` : pathKey;
    const isLast = idx === pairs.length - 1;
    const bgColor = depth === 0 && idx % 2 === 1 ? 'var(--bg-elevated)' : 'var(--bg-surface)';

    const row = document.createElement('div');
    row.style.cssText = `display:flex;align-items:center;min-height:36px;border-bottom:${isLast?'none':'1px solid var(--border-subtle)'};background:${bgColor};`;

    if (depth > 0) {
      const indent = document.createElement('div');
      indent.style.cssText = `width:${depth*20}px;flex-shrink:0;align-self:stretch;background:var(--bg-elevated);border-right:1px solid var(--border-subtle);`;
      row.appendChild(indent);
    }

    if (val && typeof val === 'object') {
      const inner = document.createElement('div');
      inner.style.cssText = 'flex:1;display:flex;align-items:center;gap:8px;padding:8px 16px;cursor:pointer;user-select:none;min-width:0;';
      const arrow = document.createElement('span');
      arrow.style.cssText = 'font-size:9px;color:var(--text-muted);width:12px;flex-shrink:0;transition:transform .12s;';
      arrow.textContent = '▶';
      const keyEl = document.createElement('span');
      keyEl.style.cssText = 'font-family:var(--font-mono);font-size:12px;font-weight:500;color:var(--text-primary);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      keyEl.textContent = rawKey;
      const typePill = document.createElement('span');
      typePill.style.cssText = 'font-size:10px;padding:2px 8px;border-radius:20px;border:1px solid var(--border-default);color:var(--text-muted);background:var(--bg-panel);flex-shrink:0;width:68px;text-align:center;box-sizing:border-box;';
      typePill.textContent = Array.isArray(val) ? 'array' : 'object';
      inner.appendChild(arrow); inner.appendChild(keyEl); inner.appendChild(typePill);
      row.appendChild(inner);
      frag.appendChild(row);

      const childWrap = document.createElement('div');
      childWrap.style.display = 'none';
      childWrap.appendChild(_buildSchemaRows(rootSchema, val, currentPath, depth + 1));
      inner.onclick = () => {
        const open = childWrap.style.display === 'none';
        childWrap.style.display = open ? '' : 'none';
        arrow.style.transform = open ? 'rotate(90deg)' : '';
      };
      frag.appendChild(childWrap);
    } else {
      const isNullish = !val || val === 'null' || val === '?';
      const dot = document.createElement('div');
      dot.style.cssText = `width:6px;height:6px;border-radius:50%;flex-shrink:0;margin:0 10px 0 16px;background:${isNullish?'var(--text-disabled)':'var(--accent)'};`;
      const keyEl = document.createElement('span');
      keyEl.style.cssText = `font-family:var(--font-mono);font-size:12px;font-weight:500;color:${isNullish?'var(--text-muted)':'var(--text-primary)'};flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`;
      keyEl.textContent = rawKey;
      const typeSelect = document.createElement('select');
      typeSelect.style.cssText = 'font-size:11px;border:1px solid var(--border-default);border-radius:4px;background:var(--bg-panel);color:var(--text-secondary);padding:2px 6px;cursor:pointer;flex-shrink:0;width:100px;margin:0 12px;';
      _TYPE_OPTS.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t; opt.textContent = t;
        if (t === val || (!val && t === 'string')) opt.selected = true;
        typeSelect.appendChild(opt);
      });
      typeSelect.onchange = () => {
        // Mutate rootSchema in-place (no API call)
        const parts = currentPath.split('.');
        let node = rootSchema;
        for (let i = 0; i < parts.length - 1; i++) {
          const p = parts[i];
          node = Array.isArray(node) ? node[parseInt(p)] : node[p];
          if (!node) return;
        }
        const last = parts[parts.length - 1];
        if (Array.isArray(node)) node[parseInt(last)] = typeSelect.value;
        else node[last] = typeSelect.value;
        const nowNull = typeSelect.value === 'null';
        dot.style.background = nowNull ? 'var(--text-disabled)' : 'var(--accent)';
        keyEl.style.color = nowNull ? 'var(--text-muted)' : 'var(--text-primary)';
      };
      row.appendChild(dot); row.appendChild(keyEl); row.appendChild(typeSelect);
      frag.appendChild(row);
    }
  });
  return frag;
}

function _buildSchemaSection(title, schemaKey, entry) {
  const sec = document.createElement('div');
  sec.style.cssText = 'margin-bottom:24px;';

  const hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;';

  const titleEl = document.createElement('span');
  titleEl.style.cssText = 'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--text-secondary);flex:1;';
  titleEl.textContent = title;
  hdr.appendChild(titleEl);

  const card = document.createElement('div');
  card.style.cssText = 'border:1px solid var(--border-default);border-radius:8px;overflow:hidden;';
  sec.appendChild(hdr);
  sec.appendChild(card);

  const hasSchema = entry[schemaKey] && typeof entry[schemaKey] === 'object' && (
    Array.isArray(entry[schemaKey]) ? entry[schemaKey].length > 0 : Object.keys(entry[schemaKey]).length > 0
  );

  if (!hasSchema) {
    const empty = document.createElement('div');
    empty.style.cssText = 'padding:16px 20px;';
    const p1 = document.createElement('p');
    p1.style.cssText = 'margin:0 0 4px;font-size:13px;color:var(--text-muted);';
    p1.textContent = schemaKey.includes('response') ? 'No response schema captured yet.' : 'No request body schema captured.';
    const p2 = document.createElement('p');
    p2.style.cssText = 'margin:0;font-size:11px;color:var(--text-disabled);line-height:1.5;';
    p2.textContent = schemaKey.includes('response')
      ? 'Run a test calling this endpoint to capture its response body schema.'
      : 'Endpoints that send a JSON body will show their schema here after recording.';
    empty.appendChild(p1); empty.appendChild(p2);
    card.appendChild(empty);
    return sec;
  }

  // Deep copy for local edits
  let localSchema = JSON.parse(JSON.stringify(entry[schemaKey]));
  let currentView = 'tree';

  // Toggle + Save controls
  const controls = document.createElement('div');
  controls.style.cssText = 'display:flex;align-items:center;gap:6px;';

  const toggle = document.createElement('div');
  toggle.style.cssText = 'display:flex;border:1px solid var(--border-default);border-radius:5px;overflow:hidden;';

  const treeTab = document.createElement('button');
  treeTab.type = 'button';
  treeTab.textContent = 'Tree';
  treeTab.style.cssText = 'border:none;padding:3px 10px;font-size:11px;cursor:pointer;';

  const jsonTab = document.createElement('button');
  jsonTab.type = 'button';
  jsonTab.textContent = 'JSON';
  jsonTab.style.cssText = 'border:none;border-left:1px solid var(--border-default);padding:3px 10px;font-size:11px;cursor:pointer;';

  toggle.appendChild(treeTab); toggle.appendChild(jsonTab);
  controls.appendChild(toggle);

  const saveBtn = _mkBtn('Save', 'btn btn-xs btn-primary');
  controls.appendChild(saveBtn);
  hdr.appendChild(controls);

  // Tree view
  const treeView = document.createElement('div');

  // JSON view
  const jsonView = document.createElement('div');
  jsonView.style.cssText = 'display:none;';
  const jsonTA = document.createElement('textarea');
  jsonTA.style.cssText = 'width:100%;min-height:180px;border:none;padding:14px 16px;font-family:var(--font-mono);font-size:12px;line-height:1.6;background:var(--bg-elevated);color:var(--text-primary);resize:vertical;box-sizing:border-box;outline:none;display:block;';
  jsonTA.spellcheck = false;
  jsonView.appendChild(jsonTA);

  card.appendChild(treeView);
  card.appendChild(jsonView);

  function _buildColHdr() {
    const ch = document.createElement('div');
    ch.style.cssText = 'display:flex;align-items:center;background:var(--bg-panel);border-bottom:1px solid var(--border-default);padding:6px 0;';
    const fh = document.createElement('div');
    fh.style.cssText = 'flex:1;padding:0 16px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);';
    fh.textContent = 'Field';
    const th = document.createElement('div');
    th.style.cssText = 'width:120px;flex-shrink:0;padding:0 12px 0 0;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);text-align:right;';
    th.textContent = 'Type';
    ch.appendChild(fh); ch.appendChild(th);
    return ch;
  }

  function _rebuildTree() {
    treeView.innerHTML = '';
    treeView.appendChild(_buildColHdr());
    treeView.appendChild(_buildSchemaRows(localSchema, localSchema, '', 0));
  }

  function _setView(mode) {
    currentView = mode;
    if (mode === 'tree') {
      try { localSchema = JSON.parse(jsonTA.value); } catch {}
      _rebuildTree();
      treeView.style.display = ''; jsonView.style.display = 'none';
      treeTab.style.cssText = 'border:none;padding:3px 10px;font-size:11px;cursor:pointer;background:var(--accent);color:#fff;';
      jsonTab.style.cssText = 'border:none;border-left:1px solid var(--border-default);padding:3px 10px;font-size:11px;cursor:pointer;background:transparent;color:var(--text-muted);';
    } else {
      jsonTA.value = JSON.stringify(localSchema, null, 2);
      treeView.style.display = 'none'; jsonView.style.display = '';
      jsonTab.style.cssText = 'border:none;border-left:1px solid var(--border-default);padding:3px 10px;font-size:11px;cursor:pointer;background:var(--accent);color:#fff;';
      treeTab.style.cssText = 'border:none;padding:3px 10px;font-size:11px;cursor:pointer;background:transparent;color:var(--text-muted);';
    }
  }
  _setView('tree');

  treeTab.onclick = () => _setView('tree');
  jsonTab.onclick = () => _setView('json');

  saveBtn.onclick = async () => {
    let schemaToSave = localSchema;
    if (currentView === 'json') {
      try { schemaToSave = JSON.parse(jsonTA.value); }
      catch { await window._alertDialog('Invalid JSON — fix syntax errors before saving.'); return; }
    }
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    const r = await window.api('PUT', `/docs/${entry.id}`, { [schemaKey]: schemaToSave });
    saveBtn.disabled = false; saveBtn.textContent = 'Save';
    if (r.ok === false) { await window._alertDialog('Save failed: ' + r.error); return; }
    entry[schemaKey] = r.entry[schemaKey];
    localSchema = JSON.parse(JSON.stringify(entry[schemaKey] || {}));
    if (currentView === 'tree') _rebuildTree();
    window._toast('Saved ✓');
  };

  return sec;
}

function _buildKvSection(title, schemaKey, entry) {
  const schema = entry[schemaKey];
  if (!schema || !Object.keys(schema).length) return null;

  const sec = document.createElement('div');
  sec.style.cssText = 'margin-bottom:24px;';

  const hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
  const titleEl = document.createElement('span');
  titleEl.style.cssText = 'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--text-secondary);flex:1;';
  titleEl.textContent = title;
  hdr.appendChild(titleEl);

  let localSchema = { ...schema };

  const saveBtn = _mkBtn('Save', 'btn btn-xs btn-primary');
  hdr.appendChild(saveBtn);

  const card = document.createElement('div');
  card.style.cssText = 'border:1px solid var(--border-default);border-radius:8px;overflow:hidden;';

  // Column header
  const colHdr = document.createElement('div');
  colHdr.style.cssText = 'display:flex;align-items:center;background:var(--bg-panel);border-bottom:1px solid var(--border-default);padding:6px 0;';
  const nameHdr = document.createElement('div');
  nameHdr.style.cssText = 'flex:1;padding:0 16px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);';
  nameHdr.textContent = 'Name';
  const typeHdr = document.createElement('div');
  typeHdr.style.cssText = 'width:120px;flex-shrink:0;padding:0 16px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);text-align:right;';
  typeHdr.textContent = 'Type';
  colHdr.appendChild(nameHdr); colHdr.appendChild(typeHdr);
  card.appendChild(colHdr);

  const pairs = Object.entries(schema);
  pairs.forEach(([k, v], idx) => {
    const row = document.createElement('div');
    row.style.cssText = `display:flex;align-items:center;border-bottom:${idx<pairs.length-1?'1px solid var(--border-subtle)':'none'};background:${idx%2===1?'var(--bg-elevated)':'var(--bg-surface)'};`;
    const dot = document.createElement('div');
    dot.style.cssText = 'width:6px;height:6px;border-radius:50%;flex-shrink:0;margin:0 10px 0 16px;background:var(--accent);';
    const nameEl = document.createElement('span');
    nameEl.style.cssText = 'font-family:var(--font-mono);font-size:12px;font-weight:500;color:var(--text-primary);flex:1;padding:9px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    nameEl.textContent = k; nameEl.title = k;
    const typeCell = document.createElement('div');
    typeCell.style.cssText = 'width:120px;flex-shrink:0;padding:6px 12px;display:flex;justify-content:flex-end;';
    const typeSelect = document.createElement('select');
    typeSelect.style.cssText = 'font-size:11px;border:1px solid var(--border-default);border-radius:4px;background:var(--bg-panel);color:var(--text-secondary);padding:2px 6px;cursor:pointer;width:100%;';
    _TYPE_OPTS.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t; opt.textContent = t;
      if (t === v) opt.selected = true;
      typeSelect.appendChild(opt);
    });
    typeSelect.onchange = () => { localSchema[k] = typeSelect.value; };
    typeCell.appendChild(typeSelect);
    row.appendChild(dot); row.appendChild(nameEl); row.appendChild(typeCell);
    card.appendChild(row);
  });

  saveBtn.onclick = async () => {
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    const r = await window.api('PUT', `/docs/${entry.id}`, { [schemaKey]: localSchema });
    saveBtn.disabled = false; saveBtn.textContent = 'Save';
    if (r.ok === false) { await window._alertDialog('Save failed: ' + r.error); return; }
    entry[schemaKey] = r.entry[schemaKey];
    localSchema = { ...entry[schemaKey] };
    window._toast('Saved ✓');
  };

  sec.appendChild(hdr);
  sec.appendChild(card);
  return sec;
}

// ── Main view ────────────────────────────────────────────────────────────

export function renderDocsView(container) {
  container.innerHTML = '';

  const layout = document.createElement('div');
  // flex:1 + min-width:0 so layout fills the parent flex container (docsPanel)
  layout.style.cssText = 'display:flex;height:100%;overflow:hidden;flex:1;min-width:0;';

  const listPanel = document.createElement('div');
  listPanel.style.cssText = 'width:300px;min-width:220px;border-right:1px solid var(--border-default);overflow:hidden;flex-shrink:0;display:flex;flex-direction:column;background:var(--bg-surface);';

  const detailPanel = document.createElement('div');
  detailPanel.style.cssText = 'flex:1;min-width:0;overflow-y:auto;background:var(--bg-base);';
  _showEmptyState(detailPanel);

  layout.appendChild(listPanel);
  layout.appendChild(detailPanel);
  container.appendChild(layout);

  let _activeItem = null;

  // ── Detail renderer ──
  function _renderDetail(entry) {
    detailPanel.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.style.cssText = 'padding:24px 32px;width:100%;box-sizing:border-box;';
    detailPanel.appendChild(wrap);

    // Endpoint header card
    const endpointHdr = document.createElement('div');
    endpointHdr.style.cssText = 'display:flex;align-items:center;gap:12px;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;padding:14px 18px;margin-bottom:18px;';
    const methodBadge = document.createElement('span');
    methodBadge.className = _methodBadgeClass(entry.method);
    methodBadge.style.cssText = 'font-size:12px;padding:5px 14px;flex-shrink:0;border-radius:5px;letter-spacing:.07em;min-width:52px;text-align:center;';
    methodBadge.textContent = entry.method;
    const pathEl = document.createElement('span');
    pathEl.style.cssText = 'font-family:var(--font-mono);font-size:14px;font-weight:500;color:var(--text-primary);word-break:break-all;flex:1;';
    pathEl.textContent = entry.path_pattern;
    endpointHdr.appendChild(methodBadge);
    endpointHdr.appendChild(pathEl);
    wrap.appendChild(endpointHdr);

    // Description (inline editable)
    const descWrap = document.createElement('div');
    descWrap.style.cssText = 'margin-bottom:18px;';
    let _editingDesc = false;

    const descView = document.createElement('div');
    descView.style.cssText = 'display:flex;align-items:flex-start;gap:10px;';
    const descText = document.createElement('p');
    descText.style.cssText = 'flex:1;font-size:13px;line-height:1.65;margin:0;';
    const editDescBtn = _mkBtn('✎ Edit', 'btn btn-xs btn-ghost');
    editDescBtn.style.cssText += ';flex-shrink:0;white-space:nowrap;';

    function _refreshDescText() {
      if (entry.description) {
        descText.textContent = entry.description;
        descText.style.color = 'var(--text-secondary)';
        descText.style.fontStyle = 'normal';
      } else {
        descText.textContent = 'No description yet — click Edit to add one';
        descText.style.color = 'var(--text-muted)';
        descText.style.fontStyle = 'italic';
      }
    }
    _refreshDescText();
    descView.appendChild(descText); descView.appendChild(editDescBtn);

    const descEditWrap = document.createElement('div');
    descEditWrap.style.display = 'none';
    const descTA = document.createElement('textarea');
    descTA.style.cssText = 'width:100%;font-size:13px;font-family:inherit;line-height:1.6;border:1px solid var(--accent);border-radius:6px;padding:8px 12px;resize:vertical;min-height:72px;box-sizing:border-box;background:var(--bg-elevated);color:var(--text-primary);outline:none;';
    descTA.placeholder = 'Describe what this endpoint does, when to use it, expected behavior…';
    const descActions = document.createElement('div');
    descActions.style.cssText = 'display:flex;gap:6px;margin-top:6px;';
    const saveDescBtn = _mkBtn('Save', 'btn btn-sm btn-primary');
    const cancelDescBtn = _mkBtn('Cancel', 'btn btn-sm btn-ghost');
    descActions.appendChild(saveDescBtn); descActions.appendChild(cancelDescBtn);
    descEditWrap.appendChild(descTA); descEditWrap.appendChild(descActions);

    function _startDescEdit() {
      if (_editingDesc) return;
      _editingDesc = true;
      descTA.value = entry.description || '';
      descView.style.display = 'none'; descEditWrap.style.display = '';
      descTA.focus();
    }
    function _cancelDescEdit() {
      _editingDesc = false; descEditWrap.style.display = 'none'; descView.style.display = 'flex';
    }
    saveDescBtn.onclick = async () => {
      const v = descTA.value.trim();
      const r = await window.api('PUT', `/docs/${entry.id}`, { description: v });
      if (r.ok === false) { await window._alertDialog('Save failed: ' + r.error); return; }
      entry.description = v; _refreshDescText(); _cancelDescEdit(); window._toast('Saved ✓');
    };
    cancelDescBtn.onclick = _cancelDescEdit;
    editDescBtn.onclick = _startDescEdit;
    descWrap.appendChild(descView); descWrap.appendChild(descEditWrap);
    wrap.appendChild(descWrap);

    // Meta chips
    const metaRow = document.createElement('div');
    metaRow.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:28px;';
    const seenAt = entry.last_seen_at
      ? new Date(entry.last_seen_at).toLocaleDateString('en-US', {month:'short',day:'numeric',year:'numeric'})
      : 'never';
    const srcCount = (entry.source_request_ids || []).length;
    metaRow.appendChild(_metaChip('Last seen', seenAt));
    metaRow.appendChild(_metaChip('Sources', `${srcCount} recording${srcCount !== 1 ? 's' : ''}`));
    wrap.appendChild(metaRow);

    // Schema sections
    wrap.appendChild(_buildSchemaSection('Request Body', 'request_schema', entry));
    wrap.appendChild(_buildSchemaSection('Response Body', 'response_schema', entry));

    // KV sections
    const paramsSec = _buildKvSection('Query Parameters', 'params_schema', entry);
    if (paramsSec) wrap.appendChild(paramsSec);
    const headersSec = _buildKvSection('Request Headers', 'headers_schema', entry);
    if (headersSec) wrap.appendChild(headersSec);

    // Footer
    const footer = document.createElement('div');
    footer.style.cssText = 'display:flex;justify-content:flex-end;margin-top:16px;padding-top:16px;border-top:1px solid var(--border-subtle);';
    const delBtn = _mkBtn('Remove from docs', 'btn btn-sm btn-ghost');
    delBtn.style.color = 'var(--danger)';
    delBtn.onclick = async () => {
      const confirmed = await window._confirmDialog(
        'Remove this endpoint?',
        `${entry.method} ${entry.path_pattern} will be removed from API documentation. Recordings are kept.`
      );
      if (!confirmed) return;
      const r = await window.api('DELETE', `/docs/${entry.id}`);
      if (r.ok === false) { await window._alertDialog('Error: ' + r.error); return; }
      _showEmptyState(detailPanel);
      _load();
    };
    footer.appendChild(delBtn);
    wrap.appendChild(footer);
  }

  // ── List loader ──
  async function _load() {
    listPanel.innerHTML = '';
    _activeItem = null;

    const loadEl = document.createElement('div');
    loadEl.style.cssText = 'flex:1;padding:14px 16px;font-size:13px;color:var(--text-muted);';
    loadEl.textContent = 'Loading…';
    listPanel.appendChild(loadEl);

    const res = await window.api('GET', '/docs');
    const entries = res.entries || [];
    listPanel.innerHTML = '';

    const listScroll = document.createElement('div');
    listScroll.style.cssText = 'flex:1;overflow-y:auto;';

    if (!entries.length) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding:28px 20px;text-align:center;';
      empty.innerHTML = '<p style="font-size:13px;color:var(--text-muted);margin:0 0 6px;">No endpoints documented yet.</p><p style="font-size:12px;color:var(--text-disabled);margin:0;">Record APIs with "Include in Documentation" checked.</p>';
      listScroll.appendChild(empty);
      listPanel.appendChild(listScroll);
      _addExportFooter();
      return;
    }

    // Group by first 2 non-param segments
    const groups = {};
    for (const e of entries) {
      const segs = e.path_pattern.split('/').filter(s => s && !s.startsWith('{'));
      const key = '/' + segs.slice(0, 2).join('/');
      (groups[key] = groups[key] || []).push(e);
    }

    function _activateItem(el, entry) {
      if (_activeItem && _activeItem !== el) {
        _activeItem.style.background = '';
        _activeItem.style.borderLeftColor = 'transparent';
        const pp = _activeItem.querySelector('.docs-path');
        if (pp) pp.style.color = 'var(--text-secondary)';
      }
      _activeItem = el;
      el.style.background = 'var(--accent-subtle)';
      el.style.borderLeftColor = 'var(--accent)';
      const p = el.querySelector('.docs-path');
      if (p) p.style.color = 'var(--text-primary)';
      _renderDetail(entry);
    }

    for (const [groupKey, groupEntries] of Object.entries(groups)) {
      const groupEl = document.createElement('div');
      groupEl.style.cssText = 'margin-top:4px;';
      const groupHdr = document.createElement('div');
      groupHdr.style.cssText = 'padding:10px 16px 4px;font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--text-muted);font-weight:700;font-family:var(--font-mono);';
      groupHdr.textContent = groupKey;
      groupEl.appendChild(groupHdr);

      for (const entry of groupEntries) {
        const item = document.createElement('div');
        item.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;border-left:3px solid transparent;transition:background .1s;';
        const badge = document.createElement('span');
        badge.className = _methodBadgeClass(entry.method);
        badge.style.cssText = 'font-size:10px;padding:2px 0;width:50px;text-align:center;flex-shrink:0;border-radius:4px;letter-spacing:.04em;';
        badge.textContent = entry.method;
        const pathEl = document.createElement('span');
        pathEl.className = 'docs-path';
        pathEl.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;transition:color .1s;';
        pathEl.textContent = entry.path_pattern;
        pathEl.title = entry.path_pattern;
        item.appendChild(badge); item.appendChild(pathEl);
        item.onmouseenter = () => { if (item !== _activeItem) item.style.background = 'var(--bg-elevated)'; };
        item.onmouseleave = () => { if (item !== _activeItem) item.style.background = ''; };
        item.onclick = () => _activateItem(item, entry);
        groupEl.appendChild(item);
      }
      listScroll.appendChild(groupEl);
    }

    listPanel.appendChild(listScroll);
    _addExportFooter();
  }

  function _addExportFooter() {
    const footer = document.createElement('div');
    footer.style.cssText = 'flex-shrink:0;border-top:1px solid var(--border-default);padding:10px 12px;';
    const btn = document.createElement('a');
    btn.href = '/api/docs/export/openapi';
    btn.download = 'openapi.yaml';
    btn.className = 'btn btn-sm btn-ghost';
    btn.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:6px;width:100%;box-sizing:border-box;text-decoration:none;';
    btn.innerHTML = '&#8659; Export OpenAPI YAML';
    footer.appendChild(btn);
    listPanel.appendChild(footer);
  }

  _load();
}
