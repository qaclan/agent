import { showVariantComparisonModal } from './variant-comparison-modal.js';

const _BODY_TYPE_LABELS = { form: 'x-www-form-urlencoded', multipart: 'form-data/multipart', graphql: 'GraphQL' };

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
    ? data.map(h => [h.name ?? h.key ?? '', h.is_file ? `📎 ${h.filename || 'file'}` : (h.value ?? '')])
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

  const _bodyPreviewValue =
    req.body_type === 'form' ? req.body_form
    : req.body_type === 'multipart' ? req.body_multipart
    : req.body_type === 'graphql' ? req.body_graphql
    : req.body;
  const bodyContent = !_bodyPreviewValue
    ? '<span style="color:var(--text-muted);font-size:12px;font-style:italic;">—</span>'
    : (req.body_type === 'form' || req.body_type === 'multipart')
      ? _kvTable(_bodyPreviewValue)
      : `<pre style="margin:0;padding:10px 12px;border-left:3px solid var(--accent);background:var(--bg-base);font-size:11px;font-family:var(--font-mono,monospace);white-space:pre-wrap;word-break:break-all;max-height:150px;overflow-y:auto;color:var(--text-primary);border-radius:0 4px 4px 0;">${_esc(_fmt(_bodyPreviewValue))}</pre>`;
  const _bodyTypeLabel = req.body_type && req.body_type !== 'raw' ? _BODY_TYPE_LABELS[req.body_type] || req.body_type : null;
  const bodySection = _section(_bodyTypeLabel ? `Request Body — ${_bodyTypeLabel}` : 'Request Body', bodyContent);

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

export function showRequestReviewModal(requests, defaultCollectionName, startUrl, extras) {
  if (!requests?.length) {
    window._alertDialog('No requests found in this file.');
    return;
  }
  const importWarnings = extras?.warnings || [];
  const collectionVars = extras?.collection_vars || null;
  const collectionAuth = extras?.collection_auth || null;
  const onSaved = extras?.onSaved || null;
  let existingCollections = [];

  const COMPOUND_SUFFIXES = new Set([
    'co.uk', 'org.uk', 'me.uk', 'ltd.uk', 'plc.uk',
    'co.in', 'com.au', 'net.au', 'org.au',
    'com.bd', 'net.bd', 'org.bd', 'gov.bd', 'edu.bd',
    'co.jp', 'co.nz', 'co.za', 'com.br', 'com.sg', 'com.mx',
  ]);

  function _rootDomain(hostname) {
    const labels = String(hostname || '').split('.').filter(Boolean);
    if (labels.length <= 2) return hostname || '';
    const lastTwo = labels.slice(-2).join('.');
    const n = COMPOUND_SUFFIXES.has(lastTwo) ? 3 : 2;
    return labels.slice(-n).join('.');
  }

  function _hostname(url) {
    try { return new URL(url).hostname; } catch { return ''; }
  }

  // Each request is classified against its OWN owning script's recorded
  // start URL (r._scriptStartUrl), not one value shared across the whole
  // modal — a suite mixing scripts recorded against different sites would
  // otherwise flag one script's real API as third-party just because
  // another script's request happened to be used as the reference. Requests
  // with no _scriptStartUrl (older import flows, single-script Record-APIs
  // mode) fall back to the modal-level startUrl param.
  function _rowRootDomain(r) {
    let hostname = '';
    try { hostname = new URL(r._scriptStartUrl || startUrl || '').hostname; } catch {}
    return _rootDomain(hostname);
  }

  const indexedRequests = requests.map((r, i) => ({ ...r, _idx: i }));
  const thirdPartyCount = indexedRequests.filter(r => {
    const rootDomain = _rowRootDomain(r);
    return rootDomain && _rootDomain(_hostname(r.url)) !== rootDomain;
  }).length
  let hidingThirdParty = false;

  function _visible() {
    if (!hidingThirdParty) return indexedRequests;
    return indexedRequests.filter(r => {
      const rootDomain = _rowRootDomain(r);
      return !rootDomain || _rootDomain(_hostname(r.url)) === rootDomain;
    });
  }

  function _renderList(listEl) {
    // Build rows as DOM nodes so we can attach handlers directly
    listEl.innerHTML = '';
    let lastGroup = undefined;
    _visible().forEach(r => {
      if (r._scriptName !== undefined && r._scriptName !== lastGroup) {
        lastGroup = r._scriptName;
        const groupHeader = document.createElement('div');
        groupHeader.style.cssText = 'padding:6px 10px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);background:var(--bg-base);border-bottom:1px solid var(--border);';
        groupHeader.textContent = lastGroup || 'Unknown script';
        listEl.appendChild(groupHeader);
      }
      const wrapper = document.createElement('div');
      wrapper.style.borderBottom = '1px solid var(--border)';

      const methodPrefix = new RegExp(`^${r.method}\\s+`, 'i');
      const displayName = (r.name || '').replace(methodPrefix, '') || r.url.replace(/\?.*/, '');
      const hostname = _hostname(r.url);
      const origin = (() => { try { return new URL(r.url).origin; } catch { return hostname; } })();
      const rowRootDomain = _rowRootDomain(r);
      const isThirdParty = rowRootDomain && _rootDomain(hostname) !== rowRootDomain;

      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;font-size:12px;';
      row.innerHTML = `
        <input type="checkbox" id="rev-req-${r._idx}" checked style="flex-shrink:0;">
        <label for="rev-req-${r._idx}" style="flex:1;cursor:pointer;min-width:0;overflow:hidden;">
          <div style="display:flex;align-items:center;gap:6px;">
            <span class="method-badge method-${_esc(r.method)}" style="font-size:10px;padding:1px 5px;flex-shrink:0;">${_esc(r.method)}</span>
            <span style="flex:1;min-width:0;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(displayName)}</span>
            <span title="${_esc(r.url)}" style="flex-shrink:0;font-size:10px;font-family:var(--font-mono,monospace);color:var(--text-muted);background:var(--bg-base);border:1px solid var(--border);border-radius:3px;padding:1px 5px;max-width:40%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;${isThirdParty ? 'color:var(--accent);border-color:var(--accent-subtle);' : ''}">${_esc(origin)}</span>
          </div>
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

  const warningsSection = importWarnings.length ? `
    <div style="background:var(--warning-bg);border:1px solid var(--warning);border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:12px;">
      <div style="font-weight:700;color:var(--warning);margin-bottom:4px;">${importWarnings.length} item${importWarnings.length !== 1 ? 's' : ''} need attention:</div>
      <ul style="margin:0;padding-left:18px;color:var(--text-secondary);">
        ${importWarnings.map(w => `<li style="margin-bottom:2px;">${_esc(w)}</li>`).join('')}
      </ul>
    </div>` : '';

  const modalBody = `
    ${warningsSection}
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">
      ${requests.length} request${requests.length !== 1 ? 's' : ''} found. Select which to save:
    </p>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
      <div style="display:flex;gap:8px;">
        <button type="button" class="btn-ghost" id="rev-all" style="font-size:11px;padding:2px 8px;">All</button>
        <button type="button" class="btn-ghost" id="rev-none" style="font-size:11px;padding:2px 8px;">None</button>
      </div>
      ${thirdPartyCount > 0 ? `
      <label style="display:flex;align-items:center;gap:5px;font-size:12px;cursor:pointer;color:var(--text-muted);">
        <input type="checkbox" id="rev-hide-3p" ${hidingThirdParty ? 'checked' : ''}>
        Hide third-party (${thirdPartyCount})
      </label>` : ''}
    </div>
    <div id="rev-list" style="max-height:480px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:12px;"></div>
    <div style="margin-bottom:10px;">
      <label class="form-label">Save to collection</label>
      <input id="rev-col-name" type="text" class="input-sm" style="width:100%"
        value="${_esc(defaultCollectionName || 'Imported APIs')}">
      <label class="form-label" style="margin-top:8px;">Or add to an existing collection</label>
      <select id="rev-col-existing" class="input-sm" style="width:100%;">
        <option value="">— New collection (name above) —</option>
      </select>
    </div>
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
      <input type="checkbox" id="rev-include-docs" checked>
      Include in API Documentation
    </label>
    <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-subtle);">
      <label style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;cursor:pointer;">
        <input type="radio" name="rev-save-mode" value="flow" checked style="margin-top:3px;">
        <span><strong>Save as Flow</strong><br><span style="font-size:11px;color:var(--text-muted)">preserve exact order + repeats — for replaying this real flow</span></span>
      </label>
      <label style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;cursor:pointer;">
        <input type="radio" name="rev-save-mode" value="library" style="margin-top:3px;">
        <span><strong>Save as Library</strong><br><span style="font-size:11px;color:var(--text-muted)">group by endpoint, show variants — for building reusable requests</span></span>
      </label>
    </div>`;

  window.showModal('Review & Save Requests', modalBody, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Save Selected', cls: 'btn-primary', action: async () => {
      const colName = document.getElementById('rev-col-name')?.value.trim() || 'Imported APIs';
      const existingColId = document.getElementById('rev-col-existing')?.value || '';
      const selected = indexedRequests.filter(r => document.getElementById(`rev-req-${r._idx}`)?.checked);
      if (!selected.length) { await window._alertDialog('No requests selected.'); return; }
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value || 'flow';

      if (mode === 'library') {
        const plainRequests = selected.map(({ _idx, _scriptName, ...rest }) => rest);
        const grouped = await window.api('POST', '/discover/group-requests', { requests: plainRequests });
        if (grouped.ok === false) { await window._alertDialog('Grouping failed: ' + grouped.error); return; }
        window._modalReturnTo = null;
        window.closeModal();
        showVariantComparisonModal(grouped.groups, colName, includeInDocs);
        return;
      }

      const plainSelected = selected.map(({ _idx, _scriptName, ...rest }) => rest);
      const data = await window.api('POST', '/discover/save-requests', {
        requests: plainSelected,
        collection_name: colName,
        collection_id: existingColId || undefined,
        include_in_docs: includeInDocs,
        collection_vars: collectionVars,
        collection_auth: collectionAuth,
      });
      if (data.ok) onSaved?.(data);
      window._modalReturnTo = null;
      window.closeModal();
      if (data.ok) {
        const targetName = existingColId
          ? (existingCollections.find(c => c.id === existingColId)?.name || colName)
          : colName;
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${targetName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
  ], null, 'lg');

  requestAnimationFrame(async () => {
    const listEl = document.getElementById('rev-list');
    if (listEl) _renderList(listEl);

    document.getElementById('rev-all')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = true));
    document.getElementById('rev-none')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = false));
    document.getElementById('rev-hide-3p')?.addEventListener('change', e => {
      hidingThirdParty = e.target.checked;
      if (listEl) _renderList(listEl);
    });

    const saveBtn = document.querySelector('[data-btn-idx="1"]');
    document.querySelectorAll('input[name="rev-save-mode"]').forEach(r => {
      r.addEventListener('change', () => {
        const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value;
        if (saveBtn) saveBtn.textContent = mode === 'library' ? 'Next →' : 'Save Selected';
      });
    });

    const existingSel = document.getElementById('rev-col-existing');
    if (existingSel) {
      const res = await window.api('GET', '/collections');
      existingCollections = res?.collections || [];
      for (const c of existingCollections) {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name;
        existingSel.appendChild(opt);
      }
    }
  });
}
