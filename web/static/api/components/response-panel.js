/**
 * createResponsePanel() → { el, show(result) }
 * result: {status_code, duration_ms, response_body, response_headers, assertion_results}
 */
export function createResponsePanel() {
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

  function _renderContent(tab) {
    if (!_currentResult) return;
    const r = _currentResult;
    contentArea.innerHTML = '';

    if (tab === 'body') {
      const pre = document.createElement('pre');
      pre.className = 'response-body-pre';
      let text = r.response_body || '';
      try {
        text = JSON.stringify(JSON.parse(text), null, 2);
      } catch(e) { /* not JSON */ }
      pre.textContent = text;
      contentArea.appendChild(pre);

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
        const actual = ar.actual !== undefined && ar.actual !== null ? ` (actual: ${_esc(String(ar.actual).slice(0,80))})` : '';
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

    // Build status line
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
    tabBar.appendChild(_renderTab(
      `Assertions (${assertPass}/${assertCount})`, 'assertions', false
    ));

    _renderContent('body');
  }

  return { el: panel, show };
}
