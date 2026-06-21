function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _renderSchemaTree(schema, path) {
  const ul = document.createElement('ul');
  ul.style.cssText = `list-style:none;margin:0;padding-left:${path ? '14px' : '0'};`;
  if (!schema || typeof schema !== 'object') {
    if (schema) {
      const li = document.createElement('li');
      li.style.cssText = 'font-family:var(--font-mono);font-size:12px;color:var(--text-muted);padding:2px 0;';
      li.textContent = String(schema);
      ul.appendChild(li);
    }
    return ul;
  }
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
      row.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;padding:1px 2px;border-radius:3px;';
      row.onmouseenter = () => row.style.background = 'var(--surface-2)';
      row.onmouseleave = () => row.style.background = '';
      const arrow = document.createElement('span');
      arrow.style.cssText = 'font-size:9px;color:var(--text-muted);width:10px;';
      arrow.textContent = '▶';
      const keySpan = document.createElement('span');
      keySpan.style.cssText = 'font-family:var(--font-mono);font-size:12px;';
      keySpan.textContent = displayKey;
      const typeTag = document.createElement('span');
      typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
      typeTag.textContent = Array.isArray(val) ? 'array' : 'object';
      row.appendChild(arrow); row.appendChild(keySpan); row.appendChild(typeTag);
      const children = _renderSchemaTree(val, currentPath);
      children.style.display = 'none';
      row.onclick = () => {
        const open = children.style.display === 'none';
        children.style.display = open ? '' : 'none';
        arrow.textContent = open ? '▼' : '▶';
      };
      li.appendChild(row); li.appendChild(children);
    } else {
      const isNullType = val === 'null' || val === '?';
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:1px 2px;';
      const dot = document.createElement('span');
      dot.style.cssText = `font-size:9px;width:10px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
      dot.textContent = '●';
      const keySpan = document.createElement('span');
      keySpan.style.cssText = `font-family:var(--font-mono);font-size:12px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
      keySpan.textContent = displayKey;
      const typeTag = document.createElement('span');
      typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
      typeTag.textContent = val || 'any';
      row.appendChild(dot); row.appendChild(keySpan); row.appendChild(typeTag);
      li.appendChild(row);
    }
    ul.appendChild(li);
  }
  return ul;
}

function _methodClass(method) {
  return `method-${(method || 'get').toLowerCase()}`;
}

export function renderDocsView(container) {
  container.innerHTML = '';

  const layout = document.createElement('div');
  layout.style.cssText = 'display:flex;height:100%;overflow:hidden;';

  // Left: endpoint list
  const listPanel = document.createElement('div');
  listPanel.style.cssText = 'width:280px;min-width:200px;border-right:1px solid var(--border);overflow-y:auto;flex-shrink:0;';

  // Right: detail
  const detailPanel = document.createElement('div');
  detailPanel.style.cssText = 'flex:1;overflow-y:auto;padding:20px 24px;';
  detailPanel.innerHTML = '<p class="text-muted text-sm">Select an endpoint to view documentation.</p>';

  layout.appendChild(listPanel);
  layout.appendChild(detailPanel);
  container.appendChild(layout);

  function _renderDetail(entry) {
    detailPanel.innerHTML = '';

    // Header
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:16px;';
    const methodBadge = document.createElement('span');
    methodBadge.className = `method-badge ${_methodClass(entry.method)}`;
    methodBadge.style.cssText = 'font-size:13px;padding:3px 10px;';
    methodBadge.textContent = entry.method;
    const pathEl = document.createElement('code');
    pathEl.style.cssText = 'font-size:15px;font-weight:500;word-break:break-all;';
    pathEl.textContent = entry.path_pattern;
    hdr.appendChild(methodBadge);
    hdr.appendChild(pathEl);
    detailPanel.appendChild(hdr);

    const meta = document.createElement('p');
    meta.style.cssText = 'font-size:11px;color:var(--text-muted);margin-bottom:16px;';
    const seenAt = entry.last_seen_at ? new Date(entry.last_seen_at).toLocaleDateString() : '—';
    meta.textContent = `Last seen: ${seenAt} · Sources: ${(entry.source_request_ids || []).length} recording(s)`;
    detailPanel.appendChild(meta);

    function _section(title, content) {
      const sec = document.createElement('div');
      sec.style.cssText = 'margin-bottom:20px;';
      const h = document.createElement('h4');
      h.style.cssText = 'font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin:0 0 8px;';
      h.textContent = title;
      sec.appendChild(h);
      const body = document.createElement('div');
      body.style.cssText = 'border:1px solid var(--border);border-radius:6px;padding:8px 12px;background:var(--surface-1,var(--bg));';
      if (typeof content === 'string') {
        body.innerHTML = `<p class="text-muted text-sm">${_esc(content)}</p>`;
      } else {
        body.appendChild(content);
      }
      sec.appendChild(body);
      detailPanel.appendChild(sec);
    }

    // Request schema
    if (entry.request_schema) {
      _section('Request Body Schema', _renderSchemaTree(entry.request_schema, ''));
    }

    // Response schema
    if (entry.response_schema) {
      _section('Response Schema', _renderSchemaTree(entry.response_schema, ''));
    } else {
      _section('Response Schema', 'Not yet captured.');
    }

    // Headers
    if (entry.headers_schema && Object.keys(entry.headers_schema).length) {
      const t = document.createElement('table');
      t.className = 'kv-table';
      t.innerHTML = '<thead><tr><th>Header</th><th>Type</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(entry.headers_schema).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      _section('Common Request Headers', t);
    }

    // Query params
    if (entry.params_schema && Object.keys(entry.params_schema).length) {
      const t = document.createElement('table');
      t.className = 'kv-table';
      t.innerHTML = '<thead><tr><th>Param</th><th>Type</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(entry.params_schema).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      _section('Query Parameters', t);
    }

    // Delete
    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-ghost';
    delBtn.style.color = 'var(--danger, #e53e3e)';
    delBtn.textContent = 'Remove from docs';
    delBtn.onclick = async () => {
      if (!confirm('Remove this endpoint from API documentation?')) return;
      const res = await window.api('DELETE', `/docs/${entry.id}`);
      if (res.ok === false) { alert('Error: ' + res.error); return; }
      detailPanel.innerHTML = '<p class="text-muted text-sm">Endpoint removed.</p>';
      _load();
    };
    detailPanel.appendChild(delBtn);
  }

  async function _load() {
    listPanel.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading…</div>';
    const res = await window.api('GET', '/docs');
    const entries = res.entries || [];
    listPanel.innerHTML = '';

    // Export button at top
    const exportBar = document.createElement('div');
    exportBar.style.cssText = 'padding:8px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:flex-end;';
    const exportBtn = document.createElement('a');
    exportBtn.href = '/api/docs/export/openapi';
    exportBtn.download = 'openapi.yaml';
    exportBtn.className = 'btn btn-xs btn-ghost';
    exportBtn.textContent = '⬇ OpenAPI YAML';
    exportBar.appendChild(exportBtn);
    listPanel.appendChild(exportBar);

    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted text-sm';
      empty.style.cssText = 'padding:12px 14px;';
      empty.textContent = 'No documented endpoints yet. Record APIs with "Include in Documentation" checked.';
      listPanel.appendChild(empty);
      return;
    }

    // Group by resource prefix (first two non-param segments)
    const groups = {};
    for (const e of entries) {
      const segs = e.path_pattern.split('/').filter(Boolean);
      const groupKey = '/' + segs.slice(0, 2).join('/');
      (groups[groupKey] = groups[groupKey] || []).push(e);
    }

    for (const [groupKey, groupEntries] of Object.entries(groups)) {
      const groupEl = document.createElement('div');
      const groupHdr = document.createElement('div');
      groupHdr.style.cssText = 'padding:6px 14px 4px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);font-weight:600;';
      groupHdr.textContent = groupKey;
      groupEl.appendChild(groupHdr);

      for (const entry of groupEntries) {
        const item = document.createElement('div');
        item.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 14px;cursor:pointer;border-radius:0;font-size:12px;';
        item.onmouseenter = () => item.style.background = 'var(--surface-2)';
        item.onmouseleave = () => item.style.background = '';
        const badge = document.createElement('span');
        badge.className = `method-badge ${_methodClass(entry.method)}`;
        badge.style.cssText = 'font-size:10px;padding:1px 5px;flex-shrink:0;';
        badge.textContent = entry.method;
        const path = document.createElement('span');
        path.style.cssText = 'font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
        path.textContent = entry.path_pattern;
        item.appendChild(badge);
        item.appendChild(path);
        item.onclick = () => {
          listPanel.querySelectorAll('[data-selected]').forEach(el => el.removeAttribute('data-selected'));
          item.setAttribute('data-selected', '1');
          item.style.background = 'var(--surface-3, var(--surface-2))';
          _renderDetail(entry);
        };
        groupEl.appendChild(item);
      }
      listPanel.appendChild(groupEl);
    }
  }

  _load();
}
