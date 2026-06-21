function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _methodBadgeClass(method) {
  return `method-badge method-${(method || 'GET').toUpperCase()}`;
}

const TYPE_OPTIONS = ['string','number','integer','boolean','null','array','object'];

export function renderDocsView(container) {
  container.innerHTML = '';

  const layout = document.createElement('div');
  layout.style.cssText = 'display:flex;height:100%;overflow:hidden;';

  // ── Left: endpoint list ──
  const listPanel = document.createElement('div');
  listPanel.style.cssText = 'width:300px;min-width:220px;border-right:1px solid var(--border-default);overflow:hidden;flex-shrink:0;display:flex;flex-direction:column;background:var(--bg-surface);';

  // ── Right: detail ──
  const detailPanel = document.createElement('div');
  detailPanel.style.cssText = 'flex:1;overflow-y:auto;background:var(--bg-base);';
  _showEmptyState(detailPanel);

  layout.appendChild(listPanel);
  layout.appendChild(detailPanel);
  container.appendChild(layout);

  let _activeItem = null;

  // ────────────────────────────────────────────────
  // Detail panel renderer
  // ────────────────────────────────────────────────
  function _renderDetail(entry) {
    detailPanel.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.style.cssText = 'padding:24px 32px;';
    detailPanel.appendChild(wrap);

    // ── Endpoint header ──
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

    // ── Description (inline editable) ──
    const descWrap = document.createElement('div');
    descWrap.style.cssText = 'margin-bottom:18px;';

    let _editingDesc = false;

    const descView = document.createElement('div');
    descView.style.cssText = 'display:flex;align-items:flex-start;gap:10px;';

    const descText = document.createElement('p');
    descText.style.cssText = 'flex:1;font-size:13px;line-height:1.65;margin:0;';

    const editDescBtn = document.createElement('button');
    editDescBtn.type = 'button';
    editDescBtn.style.cssText = 'flex-shrink:0;background:none;border:1px solid var(--border-default);border-radius:4px;padding:2px 8px;font-size:11px;color:var(--text-muted);cursor:pointer;white-space:nowrap;transition:background .1s,color .1s;';
    editDescBtn.textContent = '✎ Edit';
    editDescBtn.onmouseenter = () => { editDescBtn.style.background = 'var(--bg-elevated)'; editDescBtn.style.color = 'var(--text-primary)'; };
    editDescBtn.onmouseleave = () => { editDescBtn.style.background = 'none'; editDescBtn.style.color = 'var(--text-muted)'; };

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
    descView.appendChild(descText);
    descView.appendChild(editDescBtn);

    const descEditWrap = document.createElement('div');
    descEditWrap.style.display = 'none';

    const descTextarea = document.createElement('textarea');
    descTextarea.style.cssText = 'width:100%;font-size:13px;font-family:inherit;line-height:1.6;border:1px solid var(--accent);border-radius:6px;padding:8px 12px;resize:vertical;min-height:72px;box-sizing:border-box;background:var(--bg-elevated);color:var(--text-primary);outline:none;';
    descTextarea.placeholder = 'Describe what this endpoint does, when to use it, expected behavior…';

    const descActions = document.createElement('div');
    descActions.style.cssText = 'display:flex;gap:6px;margin-top:6px;';
    const saveDescBtn = _btn('Save', 'btn btn-sm btn-primary');
    const cancelDescBtn = _btn('Cancel', 'btn btn-sm btn-ghost');
    descActions.appendChild(saveDescBtn);
    descActions.appendChild(cancelDescBtn);
    descEditWrap.appendChild(descTextarea);
    descEditWrap.appendChild(descActions);

    function _startDescEdit() {
      if (_editingDesc) return;
      _editingDesc = true;
      descTextarea.value = entry.description || '';
      descView.style.display = 'none';
      descEditWrap.style.display = '';
      descTextarea.focus();
    }
    function _cancelDescEdit() {
      _editingDesc = false;
      descEditWrap.style.display = 'none';
      descView.style.display = 'flex';
    }
    saveDescBtn.onclick = async () => {
      const v = descTextarea.value.trim();
      const r = await window.api('PUT', `/docs/${entry.id}`, { description: v });
      if (r.ok === false) { alert('Save failed: ' + r.error); return; }
      entry.description = v;
      _refreshDescText();
      _cancelDescEdit();
    };
    cancelDescBtn.onclick = _cancelDescEdit;
    editDescBtn.onclick = _startDescEdit;

    descWrap.appendChild(descView);
    descWrap.appendChild(descEditWrap);
    wrap.appendChild(descWrap);

    // ── Metadata chips ──
    const metaRow = document.createElement('div');
    metaRow.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:28px;';

    const seenAt = entry.last_seen_at
      ? new Date(entry.last_seen_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      : 'never';
    const srcCount = (entry.source_request_ids || []).length;

    metaRow.appendChild(_metaChip('Last seen', seenAt));
    metaRow.appendChild(_metaChip('Sources', `${srcCount} recording${srcCount !== 1 ? 's' : ''}`));
    wrap.appendChild(metaRow);

    // ── Schema sections ──
    function _schemaContent(schema, schemaKey) {
      const hasData = schema && typeof schema === 'object' && (
        Array.isArray(schema) ? schema.length > 0 : Object.keys(schema).length > 0
      );
      if (!hasData) return null;

      const wrapper = document.createElement('div');

      // Column header row
      const colHdr = document.createElement('div');
      colHdr.style.cssText = 'display:flex;align-items:center;background:var(--bg-panel);border-bottom:1px solid var(--border-default);padding:6px 0;';

      const fieldHdr = document.createElement('div');
      fieldHdr.style.cssText = 'flex:1;padding:0 16px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);';
      fieldHdr.textContent = 'Field';

      const typeHdr = document.createElement('div');
      typeHdr.style.cssText = 'width:120px;flex-shrink:0;padding:0 16px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);text-align:right;';
      typeHdr.textContent = 'Type';

      colHdr.appendChild(fieldHdr);
      colHdr.appendChild(typeHdr);
      wrapper.appendChild(colHdr);

      const rows = _buildSchemaRows(schema, '', schemaKey, entry, 0);
      wrapper.appendChild(rows);
      return wrapper;
    }

    function _appendSchemaSection(title, schema, schemaKey, emptyLabel, emptyHint) {
      const content = _schemaContent(schema, schemaKey);
      if (content) {
        wrap.appendChild(_docSection(title, content));
      } else {
        wrap.appendChild(_docSection(title, null, emptyLabel, emptyHint));
      }
    }

    _appendSchemaSection('Request Body',
      entry.request_schema, 'request_schema',
      'No request body schema captured.',
      'Endpoints that send a JSON body will show their schema here after recording.');

    _appendSchemaSection('Response Body',
      entry.response_schema, 'response_schema',
      'No response schema captured yet.',
      'Run a test that calls this endpoint to capture its response body schema.');

    // Query params
    if (entry.params_schema && Object.keys(entry.params_schema).length) {
      const kvEl = _buildKvTable(entry.params_schema, 'params_schema', entry);
      wrap.appendChild(_docSection('Query Parameters', kvEl));
    }

    // Request headers
    if (entry.headers_schema && Object.keys(entry.headers_schema).length) {
      const kvEl = _buildKvTable(entry.headers_schema, 'headers_schema', entry);
      wrap.appendChild(_docSection('Request Headers', kvEl));
    }

    // ── Footer ──
    const footer = document.createElement('div');
    footer.style.cssText = 'display:flex;justify-content:flex-end;margin-top:16px;padding-top:16px;border-top:1px solid var(--border-subtle);';
    const delBtn = _btn('Remove from docs', 'btn btn-sm btn-ghost');
    delBtn.style.color = 'var(--danger)';
    delBtn.onclick = async () => {
      if (!confirm('Remove this endpoint from API documentation?')) return;
      const r = await window.api('DELETE', `/docs/${entry.id}`);
      if (r.ok === false) { alert('Error: ' + r.error); return; }
      _showEmptyState(detailPanel);
      _load();
    };
    footer.appendChild(delBtn);
    wrap.appendChild(footer);
  }

  // ────────────────────────────────────────────────
  // List loader
  // ────────────────────────────────────────────────
  async function _load() {
    listPanel.innerHTML = '';
    _activeItem = null;

    const loadingEl = document.createElement('div');
    loadingEl.style.cssText = 'flex:1;padding:14px 16px;font-size:13px;color:var(--text-muted);';
    loadingEl.textContent = 'Loading…';
    listPanel.appendChild(loadingEl);

    const res = await window.api('GET', '/docs');
    const entries = res.entries || [];
    listPanel.innerHTML = '';

    const listScroll = document.createElement('div');
    listScroll.style.cssText = 'flex:1;overflow-y:auto;';

    if (!entries.length) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding:28px 20px;text-align:center;';
      empty.innerHTML = `<p style="font-size:13px;color:var(--text-muted);margin:0 0 6px;">No endpoints documented yet.</p><p style="font-size:12px;color:var(--text-disabled);margin:0;">Record APIs with "Include in Documentation" checked.</p>`;
      listScroll.appendChild(empty);
      listPanel.appendChild(listScroll);
      _addExportFooter();
      return;
    }

    // Group by resource prefix (first 2 non-param path segments)
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
        const prev = _activeItem.querySelector('.docs-endpoint-path');
        if (prev) prev.style.color = 'var(--text-secondary)';
      }
      _activeItem = el;
      el.style.background = 'var(--accent-subtle)';
      el.style.borderLeftColor = 'var(--accent)';
      const p = el.querySelector('.docs-endpoint-path');
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
        // Fixed width so all paths align
        badge.style.cssText = 'font-size:10px;padding:2px 0;width:50px;text-align:center;flex-shrink:0;border-radius:4px;letter-spacing:.04em;';
        badge.textContent = entry.method;

        const pathEl = document.createElement('span');
        pathEl.className = 'docs-endpoint-path';
        pathEl.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;transition:color .1s;';
        pathEl.textContent = entry.path_pattern;
        pathEl.title = entry.path_pattern;

        item.appendChild(badge);
        item.appendChild(pathEl);

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
    const exportFooter = document.createElement('div');
    exportFooter.style.cssText = 'flex-shrink:0;border-top:1px solid var(--border-default);padding:10px 12px;';

    const exportBtn = document.createElement('a');
    exportBtn.href = '/api/docs/export/openapi';
    exportBtn.download = 'openapi.yaml';
    exportBtn.className = 'btn btn-sm btn-ghost';
    exportBtn.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:6px;width:100%;box-sizing:border-box;text-decoration:none;';
    exportBtn.innerHTML = '&#8659; Export OpenAPI YAML';

    exportFooter.appendChild(exportBtn);
    listPanel.appendChild(exportFooter);
  }

  _load();
}

// ── Shared helpers (module-level) ──

function _showEmptyState(panel) {
  panel.innerHTML = '';
  const el = document.createElement('div');
  el.style.cssText = 'display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;';
  el.innerHTML = '<div style="font-size:28px;opacity:.18;">&#128196;</div><p style="color:var(--text-muted);font-size:13px;margin:0;">Select an endpoint to view its documentation</p>';
  panel.appendChild(el);
}

function _btn(label, cls) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.textContent = label;
  return b;
}

function _metaChip(label, value) {
  const chip = document.createElement('div');
  chip.style.cssText = 'display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border-default);border-radius:20px;padding:3px 10px 3px 8px;background:var(--bg-elevated);';
  const lbl = document.createElement('span');
  lbl.style.cssText = 'font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted);font-weight:600;';
  lbl.textContent = label;
  const val = document.createElement('span');
  val.style.cssText = 'font-size:12px;color:var(--text-secondary);font-weight:500;';
  val.textContent = value;
  chip.appendChild(lbl);
  chip.appendChild(val);
  return chip;
}

function _docSection(title, contentEl, emptyLabel, emptyHint) {
  const sec = document.createElement('div');
  sec.style.cssText = 'margin-bottom:24px;';

  const hdr = document.createElement('div');
  hdr.style.cssText = 'margin-bottom:8px;';
  const titleEl = document.createElement('span');
  titleEl.style.cssText = 'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--text-secondary);';
  titleEl.textContent = title;
  hdr.appendChild(titleEl);
  sec.appendChild(hdr);

  const card = document.createElement('div');
  card.style.cssText = 'border:1px solid var(--border-default);border-radius:8px;overflow:hidden;';

  if (contentEl) {
    card.appendChild(contentEl);
  } else {
    const empty = document.createElement('div');
    empty.style.cssText = 'padding:16px 20px;';
    const p1 = document.createElement('p');
    p1.style.cssText = 'margin:0;font-size:13px;color:var(--text-muted);';
    p1.textContent = emptyLabel || 'Not captured.';
    empty.appendChild(p1);
    if (emptyHint) {
      const p2 = document.createElement('p');
      p2.style.cssText = 'margin:5px 0 0;font-size:11px;color:var(--text-disabled);line-height:1.5;';
      p2.textContent = emptyHint;
      empty.appendChild(p2);
    }
    card.appendChild(empty);
  }

  sec.appendChild(card);
  return sec;
}

function _buildSchemaRows(schema, path, schemaKey, entry, depth) {
  const frag = document.createDocumentFragment();
  if (!schema || typeof schema !== 'object') return frag;

  const isArr = Array.isArray(schema);
  const pairs = isArr
    ? (schema.length ? [['[item]', schema[0]]] : [])
    : Object.entries(schema);

  pairs.forEach(([rawKey, val], idx) => {
    const pathKey = isArr ? '0' : rawKey;
    const currentPath = path ? `${path}.${pathKey}` : pathKey;
    const isLast = idx === pairs.length - 1;

    const row = document.createElement('div');
    const bgColor = depth === 0 && idx % 2 === 1 ? 'var(--bg-elevated)' : 'var(--bg-surface)';
    row.style.cssText = `display:flex;align-items:center;min-height:36px;border-bottom:${isLast ? 'none' : '1px solid var(--border-subtle)'};background:${bgColor};`;

    // Indent
    if (depth > 0) {
      const indent = document.createElement('div');
      indent.style.cssText = `width:${depth * 20}px;flex-shrink:0;align-self:stretch;background:var(--bg-elevated);border-right:1px solid var(--border-subtle);`;
      row.appendChild(indent);
    }

    if (val && typeof val === 'object') {
      // Expandable: object or array
      const inner = document.createElement('div');
      inner.style.cssText = `flex:1;display:flex;align-items:center;gap:8px;padding:8px 16px;cursor:pointer;user-select:none;min-width:0;`;

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
      childWrap.style.cssText = 'display:none;';
      const childRows = _buildSchemaRows(val, currentPath, schemaKey, entry, depth + 1);
      childWrap.appendChild(childRows);

      inner.onclick = () => {
        const open = childWrap.style.display === 'none';
        childWrap.style.display = open ? '' : 'none';
        arrow.style.transform = open ? 'rotate(90deg)' : '';
      };
      frag.appendChild(childWrap);

    } else {
      // Leaf field
      const isNullish = !val || val === 'null' || val === '?';

      const dot = document.createElement('div');
      dot.style.cssText = `width:6px;height:6px;border-radius:50%;flex-shrink:0;margin:0 10px 0 16px;background:${isNullish ? 'var(--text-disabled)' : 'var(--accent)'};`;

      const keyEl = document.createElement('span');
      keyEl.style.cssText = `font-family:var(--font-mono);font-size:12px;font-weight:500;color:${isNullish ? 'var(--text-muted)' : 'var(--text-primary)'};flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`;
      keyEl.textContent = rawKey;

      const typeSelect = document.createElement('select');
      typeSelect.style.cssText = 'font-size:11px;border:1px solid var(--border-default);border-radius:4px;background:var(--bg-panel);color:var(--text-secondary);padding:2px 6px;cursor:pointer;flex-shrink:0;width:100px;margin:0 12px;';
      TYPE_OPTIONS.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t; opt.textContent = t;
        if (t === val || (!val && t === 'string')) opt.selected = true;
        typeSelect.appendChild(opt);
      });
      typeSelect.onchange = async () => {
        const newType = typeSelect.value;
        const updated = JSON.parse(JSON.stringify(entry[schemaKey] || {}));
        const parts = currentPath.split('.');
        let node = updated;
        for (let i = 0; i < parts.length - 1; i++) {
          const p = parts[i];
          node = Array.isArray(node) ? node[parseInt(p)] : node[p];
          if (!node) break;
        }
        const last = parts[parts.length - 1];
        if (Array.isArray(node)) node[parseInt(last)] = newType;
        else if (node) node[last] = newType;
        const r = await window.api('PUT', `/docs/${entry.id}`, { [schemaKey]: updated });
        if (r.ok === false) { alert('Save failed: ' + r.error); typeSelect.value = val; return; }
        entry[schemaKey] = r.entry[schemaKey];
        const nowNull = newType === 'null';
        dot.style.background = nowNull ? 'var(--text-disabled)' : 'var(--accent)';
        keyEl.style.color = nowNull ? 'var(--text-muted)' : 'var(--text-primary)';
      };

      row.appendChild(dot); row.appendChild(keyEl); row.appendChild(typeSelect);
      frag.appendChild(row);
    }
  });

  return frag;
}

function _buildKvTable(schema, schemaKey, entry) {
  const wrapper = document.createElement('div');

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
  wrapper.appendChild(colHdr);

  const pairs = Object.entries(schema);
  pairs.forEach(([k, v], idx) => {
    const row = document.createElement('div');
    const bgColor = idx % 2 === 1 ? 'var(--bg-elevated)' : 'var(--bg-surface)';
    row.style.cssText = `display:flex;align-items:center;border-bottom:${idx < pairs.length - 1 ? '1px solid var(--border-subtle)' : 'none'};background:${bgColor};`;

    const dot = document.createElement('div');
    dot.style.cssText = 'width:6px;height:6px;border-radius:50%;flex-shrink:0;margin:0 10px 0 16px;background:var(--accent);';

    const nameEl = document.createElement('span');
    nameEl.style.cssText = 'font-family:var(--font-mono);font-size:12px;font-weight:500;color:var(--text-primary);flex:1;padding:9px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    nameEl.textContent = k;
    nameEl.title = k;

    const typeCell = document.createElement('div');
    typeCell.style.cssText = 'width:120px;flex-shrink:0;padding:6px 12px;display:flex;justify-content:flex-end;';

    const typeSelect = document.createElement('select');
    typeSelect.style.cssText = 'font-size:11px;border:1px solid var(--border-default);border-radius:4px;background:var(--bg-panel);color:var(--text-secondary);padding:2px 6px;cursor:pointer;width:100%;';
    TYPE_OPTIONS.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t; opt.textContent = t;
      if (t === v) opt.selected = true;
      typeSelect.appendChild(opt);
    });
    typeSelect.onchange = async () => {
      const updated = { ...entry[schemaKey], [k]: typeSelect.value };
      const r = await window.api('PUT', `/docs/${entry.id}`, { [schemaKey]: updated });
      if (r.ok === false) { alert('Save failed: ' + r.error); typeSelect.value = v; return; }
      entry[schemaKey] = r.entry[schemaKey];
    };

    typeCell.appendChild(typeSelect);
    row.appendChild(dot); row.appendChild(nameEl); row.appendChild(typeCell);
    wrapper.appendChild(row);
  });

  return wrapper;
}
