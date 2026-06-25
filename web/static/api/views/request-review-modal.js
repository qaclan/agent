function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function _fmt(val) {
  if (!val) return '';
  if (typeof val === 'string') {
    try { return JSON.stringify(JSON.parse(val), null, 2); } catch { return val; }
  }
  try { return JSON.stringify(val, null, 2); } catch { return String(val); }
}

function _parseJson(val) {
  if (!val) return val;
  if (typeof val === 'string') { try { return JSON.parse(val); } catch { return val; } }
  return val;
}

function _kvTable(data) {
  data = _parseJson(data);
  if (!data) return '<span style="color:var(--text-muted);font-size:12px;font-style:italic;">—</span>';
  const entries = Array.isArray(data)
    ? data.map(h => [h.name ?? h.key ?? '', h.value ?? ''])
    : Object.entries(data);
  if (!entries.length) return '<span style="color:var(--text-muted);font-size:12px;font-style:italic;">—</span>';
  return `<div style="font-size:12px;">
    <div style="display:grid;grid-template-columns:minmax(80px,160px) 1fr;border-bottom:1px solid var(--border-strong);">
      <span style="font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);padding:3px 10px 3px 0;">Key</span>
      <span style="font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);padding:3px 0;">Value</span>
    </div>
    ${entries.map(([k, v], i) => `
      <div style="display:grid;grid-template-columns:minmax(80px,160px) 1fr;padding:5px 0;${i < entries.length - 1 ? 'border-bottom:1px solid var(--border-subtle);' : ''}">
        <span style="color:var(--accent);font-family:var(--font-mono,monospace);font-size:11px;padding-right:10px;word-break:break-all;">${_esc(k)}</span>
        <span style="color:var(--text-primary);word-break:break-all;">${_esc(String(v ?? ''))}</span>
      </div>`).join('')}
  </div>`;
}

function _section(label, content) {
  return `
    <div style="margin-bottom:14px;">
      <div style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">${label}</div>
      ${content}
    </div>`;
}

function _detailHTML(req) {
  let assertions = _parseJson(req.assertions);
  if (!Array.isArray(assertions)) assertions = [];

  const urlSection = _section('URL',
    `<code style="font-size:11px;word-break:break-all;color:var(--text-primary);font-family:var(--font-mono,monospace);line-height:1.6;">${_esc(req.url)}</code>`);

  const headersSection = _section('Headers', _kvTable(req.headers));
  const paramsSection  = _section('Query Params', _kvTable(req.params));

  const bodyContent = req.body
    ? `<pre style="margin:0;padding:10px 12px;border-left:3px solid var(--accent);background:var(--bg-base);font-size:11px;font-family:var(--font-mono,monospace);white-space:pre-wrap;word-break:break-all;max-height:150px;overflow-y:auto;color:var(--text-primary);border-radius:0 4px 4px 0;">${_esc(_fmt(req.body))}</pre>`
    : '<span style="color:var(--text-muted);font-size:12px;font-style:italic;">—</span>';
  const bodySection = _section('Request Body', bodyContent);

  const assertionsSection = assertions.length ? _section('Assertions',
    assertions.map(a => `
      <div style="display:flex;align-items:flex-start;gap:8px;padding:4px 0;border-bottom:1px solid var(--border-subtle);font-size:12px;">
        <span style="color:var(--accent);flex-shrink:0;">✓</span>
        <span style="color:var(--text-primary);">${_esc(typeof a === 'string' ? a : JSON.stringify(a))}</span>
      </div>`).join('')) : '';

  const descSection = req.description
    ? `<p style="font-size:12px;color:var(--text-secondary);margin:0 0 12px;line-height:1.6;border-left:3px solid var(--border-strong);padding-left:10px;">${_esc(req.description)}</p>`
    : '';

  return `
    <div style="padding:12px 16px 16px;border-top:2px solid var(--accent-subtle);">
      ${descSection}
      ${urlSection}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        ${headersSection}
        ${paramsSection}
      </div>
      ${bodySection}
      ${assertionsSection}
    </div>`;
}

export function showRequestReviewModal(requests, defaultCollectionName) {
  if (!requests?.length) {
    window._alertDialog('No requests found in this file.');
    return;
  }

  const indexedRequests = requests.map((r, i) => ({ ...r, _idx: i }));

  function _renderList(listEl) {
    // Build rows as DOM nodes so we can attach handlers directly
    listEl.innerHTML = '';
    indexedRequests.forEach(r => {
      const wrapper = document.createElement('div');
      wrapper.style.borderBottom = '1px solid var(--border)';

      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;font-size:12px;';
      row.innerHTML = `
        <input type="checkbox" id="rev-req-${r._idx}" checked style="flex-shrink:0;">
        <label for="rev-req-${r._idx}" style="flex:1;cursor:pointer;min-width:0;overflow:hidden;">
          <span class="method-badge method-${_esc(r.method)}" style="font-size:10px;padding:1px 5px;">${_esc(r.method)}</span>
          <span style="margin-left:4px;">${_esc(r.name || r.url.replace(/\?.*/, ''))}</span>
          ${r.name ? `<span style="color:var(--text-muted);margin-left:4px;font-size:10px;">${_esc(r.url.replace(/\?.*/, ''))}</span>` : ''}
        </label>
        <button type="button" class="btn-ghost" style="font-size:10px;padding:2px 7px;flex-shrink:0;">Details ▾</button>`;

      const detailPanel = document.createElement('div');
      detailPanel.style.display = 'none';
      detailPanel.innerHTML = _detailHTML(r);

      const btn = row.querySelector('button');
      let open = false;
      btn.onclick = e => {
        e.preventDefault();
        e.stopPropagation();
        open = !open;
        detailPanel.style.display = open ? '' : 'none';
        btn.textContent = open ? 'Details ▴' : 'Details ▾';
      };

      wrapper.appendChild(row);
      wrapper.appendChild(detailPanel);
      listEl.appendChild(wrapper);
    });
  }

  const modalBody = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">
      ${requests.length} request${requests.length !== 1 ? 's' : ''} found. Select which to save:
    </p>
    <div style="display:flex;gap:8px;margin-bottom:6px;">
      <button type="button" class="btn-ghost" id="rev-all" style="font-size:11px;padding:2px 8px;">All</button>
      <button type="button" class="btn-ghost" id="rev-none" style="font-size:11px;padding:2px 8px;">None</button>
    </div>
    <div id="rev-list" style="max-height:480px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:12px;"></div>
    <div style="margin-bottom:10px;">
      <label class="form-label">Save to collection</label>
      <input id="rev-col-name" type="text" class="input-sm" style="width:100%"
        value="${_esc(defaultCollectionName || 'Imported APIs')}">
    </div>
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
      <input type="checkbox" id="rev-include-docs" checked>
      Include in API Documentation
    </label>`;

  window.showModal('Review & Save Requests', modalBody, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Save Selected', cls: 'btn-primary', action: async () => {
      const colName = document.getElementById('rev-col-name')?.value.trim() || 'Imported APIs';
      const selected = indexedRequests.filter(r => document.getElementById(`rev-req-${r._idx}`)?.checked);
      if (!selected.length) { await window._alertDialog('No requests selected.'); return; }
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const data = await window.api('POST', '/discover/save-requests', {
        requests: selected,
        collection_name: colName,
        include_in_docs: includeInDocs,
      });
      window.closeModal();
      if (data.ok) {
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${colName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
  ], null, 'lg');

  requestAnimationFrame(() => {
    const listEl = document.getElementById('rev-list');
    if (listEl) _renderList(listEl);

    document.getElementById('rev-all')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = true));
    document.getElementById('rev-none')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = false));
  });
}
