function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showHarImport() {
  const body = `
    <div id="har-drop-zone" style="border:2px dashed var(--border);border-radius:8px;padding:32px;text-align:center;cursor:pointer;margin-bottom:12px;">
      <p style="margin:0;color:var(--text-muted)">Drag & drop .har file here, or <strong>click to browse</strong></p>
      <input type="file" id="har-file-input" accept=".har,application/json" style="display:none">
    </div>
    <div id="har-preview" style="display:none">
      <p id="har-summary" style="font-size:13px;color:var(--text-muted)"></p>
      <div id="har-request-list" style="max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;"></div>
    </div>`;

  window.showModal('Import HAR', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import Selected', cls: 'btn-primary', action: _doImport },
  ]);

  let _parsedRequests = [];

  requestAnimationFrame(() => {
    const dropZone = document.getElementById('har-drop-zone');
    const fileInput = document.getElementById('har-file-input');

    dropZone.onclick = () => fileInput.click();
    fileInput.onchange = (e) => e.target.files[0] && _loadHarFile(e.target.files[0]);

    dropZone.ondragover = (e) => { e.preventDefault(); dropZone.style.borderColor = 'var(--primary)'; };
    dropZone.ondragleave = () => { dropZone.style.borderColor = 'var(--border)'; };
    dropZone.ondrop = (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border)';
      const f = e.dataTransfer.files[0];
      if (f) _loadHarFile(f);
    };
  });

  async function _loadHarFile(file) {
    const text = await file.text();
    let har;
    try { har = JSON.parse(text); } catch(e) { alert('Invalid HAR file'); return; }

    const entries = har.log?.entries || [];
    const preview = document.getElementById('har-preview');
    const summary = document.getElementById('har-summary');
    const list = document.getElementById('har-request-list');

    summary.textContent = `Found ${entries.length} network entries. Static assets unchecked by default.`;
    list.innerHTML = '';
    _parsedRequests = [];

    entries.forEach((entry, i) => {
      const req = entry.request || {};
      const method = req.method || 'GET';
      const url = req.url || '';
      const isStatic = /\.(css|js|png|jpg|jpeg|gif|ico|woff|woff2|svg|webp)$/i.test(url)
                    || url.includes('/static/');

      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);font-size:12px;';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !isStatic;
      cb.id = `har-req-${i}`;

      const label = document.createElement('label');
      label.htmlFor = `har-req-${i}`;
      label.style.cssText = 'flex:1;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      label.innerHTML = `<span class="method-badge method-${_esc(method)}" style="font-size:10px;padding:1px 5px;">${_esc(method)}</span> ${_esc(url.replace(/\?.*/, ''))}`;

      row.appendChild(cb);
      row.appendChild(label);
      list.appendChild(row);
      _parsedRequests.push({ entry, cb });
    });

    preview.style.display = '';
    window._harData = har;
    window._harFile = file;
  }

  async function _doImport() {
    if (!window._harFile) { alert('Please select a HAR file first.'); return; }

    // Build filtered HAR with only checked entries
    const har = window._harData;
    har.log.entries = har.log.entries.filter((_, i) => {
      return _parsedRequests[i]?.cb?.checked;
    });

    const formData = new FormData();
    formData.append('file', new Blob([JSON.stringify(har)], { type: 'application/json' }), 'import.har');
    formData.append('collection_name', window._harFile.name.replace('.har', ''));

    const res = await fetch('/api/discover/har', { method: 'POST', body: formData });
    const data = await res.json();
    window.closeModal();
    if (data.ok) {
      alert(`Imported ${data.imported} requests.`);
    } else {
      alert('Import failed: ' + data.error);
    }
  }
}
