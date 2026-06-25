/**
 * createResponsePanel(opts?) → { el, show(result) }
 * opts.schema: response_schema dict from stored request (shown read-only in Schema tab)
 */
export function createResponsePanel(opts = {}) {
  const _storedSchema = opts.schema || null;

  const panel = document.createElement('div');
  panel.className = 'response-panel';
  panel.style.display = 'none';

  const tabBar = document.createElement('div');
  tabBar.className = 'response-tabs';
  panel.appendChild(tabBar);

  const contentArea = document.createElement('div');
  contentArea.className = 'response-content';
  panel.appendChild(contentArea);

  let _currentResult = null;

  function _renderTab(label, key, active) {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'response-tab' + (active ? ' active' : '');
    tab.textContent = label;
    tab.onclick = () => {
      tabBar.querySelectorAll('.response-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _renderContent(key);
    };
    return tab;
  }

  function _esc(s) {
    return String(s || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }

  function _renderSchemaTree(schema, path) {
    const ul = document.createElement('ul');
    ul.style.cssText = `list-style:none;margin:0;padding-left:${path ? '14px' : '0'};`;
    const isArray = Array.isArray(schema);
    const entries = isArray
      ? (schema.length ? [['0', schema[0]]] : [['0', '?']])
      : (schema && typeof schema === 'object' ? Object.entries(schema) : []);
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
        row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:1px 2px;border-radius:3px;';
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

  let _bodyView = 'body';   // 'body' | 'schema'
  let _schemaView = 'tree'; // 'tree' | 'json'

  function _mkPillGroup(items, activeKey, onClick) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:inline-flex;gap:0;';
    items.forEach(([label, key], i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      const active = activeKey === key;
      const first = i === 0, last = i === items.length - 1;
      b.style.cssText = `font-size:10px;padding:2px 10px;border:1px solid var(--border);cursor:pointer;`
        + `background:${active ? 'var(--accent)' : 'transparent'};`
        + `color:${active ? '#fff' : 'var(--text-muted)'};`
        + `border-radius:${first ? '4px 0 0 4px' : last ? '0 4px 4px 0' : '0'};`
        + (first ? '' : 'border-left:none;');
      b.onclick = () => onClick(key);
      wrap.appendChild(b);
    });
    return wrap;
  }

  function _renderSchemaSection(schema) {
    contentArea.innerHTML = '';
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border-bottom:1px solid var(--border-subtle,var(--border));';
    const title = document.createElement('span');
    title.style.cssText = 'font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;';
    title.textContent = 'Response Schema';
    const toggle = _mkPillGroup([['Tree','tree'],['JSON','json']], _schemaView, v => { _schemaView = v; _renderSchemaSection(schema); });
    header.appendChild(title);
    header.appendChild(toggle);
    contentArea.appendChild(header);
    const body = document.createElement('div');
    body.style.cssText = 'padding:8px 10px;font-size:12px;overflow:auto;';
    if (_schemaView === 'json') {
      const pre = document.createElement('pre');
      pre.className = 'response-body-pre';
      pre.style.margin = '0';
      pre.textContent = JSON.stringify(schema, null, 2);
      body.appendChild(pre);
    } else {
      body.appendChild(_renderSchemaTree(schema, ''));
    }
    contentArea.appendChild(body);
  }

  function _renderBodyOrSchema() {
    if (!_currentResult) return;
    const r = _currentResult;
    contentArea.innerHTML = '';

    const schema = r._responseSchema || _storedSchema;
    const hasSchema = schema && typeof schema === 'object' && Object.keys(schema).length;

    // Body/Schema pill toggle row (only when schema exists)
    if (hasSchema) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:flex-end;padding:4px 8px 0;';
      row.appendChild(_mkPillGroup([['Body','body'],['Schema','schema']], _bodyView, v => { _bodyView = v; _renderBodyOrSchema(); }));
      contentArea.appendChild(row);
    }

    if (_bodyView === 'schema' && hasSchema) {
      const schemaHeader = document.createElement('div');
      schemaHeader.style.cssText = 'display:flex;align-items:center;justify-content:flex-end;padding:4px 8px 2px;';
      schemaHeader.appendChild(_mkPillGroup([['Tree','tree'],['JSON','json']], _schemaView, v => { _schemaView = v; _renderBodyOrSchema(); }));
      contentArea.appendChild(schemaHeader);
      const schemaBody = document.createElement('div');
      schemaBody.style.cssText = 'padding:8px 10px;font-size:12px;overflow:auto;';
      if (_schemaView === 'json') {
        const pre = document.createElement('pre');
        pre.className = 'response-body-pre';
        pre.style.margin = '0';
        pre.textContent = JSON.stringify(schema, null, 2);
        schemaBody.appendChild(pre);
      } else {
        schemaBody.appendChild(_renderSchemaTree(schema, ''));
      }
      contentArea.appendChild(schemaBody);
      return;
    }

    // Body view
    if (!r.status_code && r.error_message) {
      const errDiv = document.createElement('div');
      errDiv.className = 'response-error-message';
      errDiv.textContent = r.error_message;
      contentArea.appendChild(errDiv);
      return;
    }
    const pre = document.createElement('pre');
    pre.className = 'response-body-pre';
    let text = r.response_body || '';
    try { text = JSON.stringify(JSON.parse(text), null, 2); } catch(e) {}
    pre.textContent = text;
    contentArea.appendChild(pre);
  }

  function _renderContent(tab) {
    if (!_currentResult) return;
    const r = _currentResult;
    contentArea.innerHTML = '';

    if (tab === 'body') {
      _bodyView = 'body';
      _renderBodyOrSchema();
      return;

    } else if (tab === 'response-schema') {
      const schema = r._responseSchema || _storedSchema;
      if (schema) _renderSchemaSection(schema);
      return;

    } else if (tab === 'headers') {
      const headers = r.response_headers || {};
      const table = document.createElement('table');
      table.className = 'kv-table';
      table.innerHTML = '<thead><tr><th>Header</th><th>Value</th></tr></thead>';
      const tbody = document.createElement('tbody');
      Object.entries(headers).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      contentArea.appendChild(table);

    } else if (tab === 'vars') {
      const updates = r.state_updates || {};
      const rows = Object.entries(updates);
      if (!rows.length) {
        contentArea.innerHTML = '<p class="text-muted text-sm" style="padding:10px">No variables extracted.</p>';
        return;
      }
      const table = document.createElement('table');
      table.className = 'kv-table';
      table.innerHTML = '<thead><tr><th>Variable</th><th>Saved Value</th></tr></thead>';
      const tbody = document.createElement('tbody');
      rows.forEach(([k, v]) => {
        const tr = document.createElement('tr');
        const valStr = String(v);
        const display = valStr.length > 80 ? valStr.slice(0, 77) + '…' : valStr;
        tr.innerHTML = `<td style="font-family:var(--font-mono);font-weight:600">${_esc(k)}</td><td style="font-family:var(--font-mono);color:var(--text-secondary)">${_esc(display)}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      contentArea.appendChild(table);

    } else if (tab === 'assertions') {
      const results = r.assertion_results || [];
      if (!results.length) {
        contentArea.innerHTML = '<p class="text-muted text-sm">No assertions configured.</p>';
        return;
      }
      results.forEach(ar => {
        const row = document.createElement('div');
        row.className = 'assertion-result-row ' + (ar.passed ? 'assertion-pass' : 'assertion-fail');
        const icon = ar.passed ? '✓' : '✗';
        const detail = ar.path ? `${ar.path} ` : ar.key ? `${ar.key} ` : '';
        const actual = ar.actual !== undefined && ar.actual !== null
          ? ` (actual: ${_esc(String(ar.actual).slice(0,80))})` : '';
        row.innerHTML = `<span class="assertion-icon">${icon}</span>
          <span class="assertion-desc">${_esc(ar.type)} ${detail}${_esc(ar.op)} ${_esc(String(ar.value ?? ''))}</span>
          <span class="assertion-actual">${actual}</span>`;
        contentArea.appendChild(row);
      });

    }
  }

  function show(result) {
    _currentResult = result;
    panel.style.display = '';

    const statusCode = result.status_code;
    const duration = result.duration_ms;
    const assertCount = (result.assertion_results || []).length;
    const assertPass = (result.assertion_results || []).filter(a => a.passed).length;
    const statusClass = statusCode >= 200 && statusCode < 300 ? 'response-status-ok'
                      : statusCode >= 400 ? 'response-status-err' : 'response-status-warn';

    tabBar.innerHTML = '';

    const statusSpan = document.createElement('span');
    statusSpan.className = `response-status ${statusClass}`;
    statusSpan.textContent = statusCode ? `${statusCode} · ${duration}ms` : `ERROR · ${duration}ms`;
    tabBar.appendChild(statusSpan);

    tabBar.appendChild(_renderTab('Body', 'body', true));
    tabBar.appendChild(_renderTab('Headers', 'headers', false));
    tabBar.appendChild(_renderTab(`Assertions (${assertPass}/${assertCount})`, 'assertions', false));
    const _varCount = Object.keys(result.state_updates || {}).length;
    if (_varCount) tabBar.appendChild(_renderTab(`Variables (${_varCount})`, 'vars', false));

    _renderContent('body');
  }

  // Show Response Schema tab before a run if stored schema exists
  if (_storedSchema) {
    panel.style.display = '';
    tabBar.innerHTML = '';
    const statusSpan = document.createElement('span');
    statusSpan.className = 'response-status';
    statusSpan.textContent = 'Not yet run';
    statusSpan.style.cssText = 'color:var(--text-muted);font-size:11px;padding:4px 8px;';
    tabBar.appendChild(statusSpan);
    tabBar.appendChild(_renderTab('Response Schema', 'response-schema', true));
    _currentResult = {};
    _renderSchemaSection(_storedSchema);
  }

  return { el: panel, show };
}
