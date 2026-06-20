function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showRecordApis() {
  const body = `
    <div id="record-status-area">
      <p style="color:var(--text-muted);font-size:13px">Starting browser... this may take a moment.</p>
    </div>`;

  window.showModal('Record APIs', body, [
    { label: 'Stop Recording', cls: 'btn-outline-danger', action: _stopRecording },
    { label: 'Cancel', cls: 'btn-ghost', action: () => { _stopRecording(); window.closeModal(); } },
  ], null, 'md');

  let _sessionId = null;
  let _pollTimer = null;
  let _captured = 0;

  async function _startRecording() {
    const res = await window.api('POST', '/discover/record/start', { url: 'about:blank' });
    const statusArea = document.getElementById('record-status-area');
    if (!statusArea) return;

    if (!res.ok) {
      statusArea.innerHTML = `<p style="color:var(--danger)">Failed to start recording: ${_esc(res.error)}</p>`;
      return;
    }

    _sessionId = res.session_id;
    statusArea.innerHTML = `
      <div class="record-status-badge recording">⏺ Recording</div>
      <p style="margin-top:10px;font-size:13px;color:var(--text-muted)">
        Interact with the browser window. Network requests are being captured.
      </p>
      <p id="record-count" style="font-size:13px">Captured: <strong>0</strong> requests</p>`;

    _pollTimer = setInterval(_pollStatus, 3000);
  }

  async function _pollStatus() {
    if (!_sessionId) return;
    const res = await window.api('GET', `/discover/record/status?session_id=${_sessionId}`);
    if (!res.ok) return;
    if (res.status === 'stopped') {
      clearInterval(_pollTimer);
      document.getElementById('record-status-area').innerHTML =
        '<div class="record-status-badge stopped">● Stopped</div>';
    }
  }

  async function _stopRecording() {
    if (_pollTimer) clearInterval(_pollTimer);
    if (!_sessionId) { window.closeModal(); return; }

    const res = await window.api('POST', '/discover/record/stop', { session_id: _sessionId });
    _sessionId = null;

    window.closeModal();

    if (!res.ok || !res.requests?.length) {
      alert('No API requests captured.');
      return;
    }

    _showCapturedResults(res.requests);
  }

  function _showCapturedResults(requests) {
    const body = `
      <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">${requests.length} requests captured. Select which to save:</p>
      <div id="captured-list" style="max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;">
        ${requests.map((r, i) => `
          <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);font-size:12px;">
            <input type="checkbox" id="cap-${i}" checked>
            <label for="cap-${i}" style="flex:1;cursor:pointer">
              <span class="method-badge method-${_esc(r.method)}" style="font-size:10px;padding:1px 5px;">${_esc(r.method)}</span>
              ${_esc(r.url.replace(/\?.*/, ''))}
            </label>
          </div>`).join('')}
      </div>
      <div style="margin-top:10px;">
        <label class="form-label">Collection name</label>
        <input id="capture-col-name" type="text" class="input-sm" style="width:100%" value="Recorded APIs">
      </div>`;

    window.showModal('Save Captured Requests', body, [
      { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
      { label: 'Save Selected', cls: 'btn-primary', action: async () => {
        const colName = document.getElementById('capture-col-name').value.trim() || 'Recorded APIs';
        const selected = requests.filter((_, i) => document.getElementById(`cap-${i}`)?.checked);
        if (!selected.length) { alert('No requests selected.'); return; }

        // Build a minimal HAR from selected requests and POST to /discover/har
        const har = {
          log: {
            version: '1.2',
            entries: selected.map(r => ({
              request: {
                method: r.method,
                url: r.url,
                headers: (r.headers || []).map(h => ({ name: h.key, value: h.value })),
                queryString: (r.params || []).map(p => ({ name: p.key, value: p.value })),
                postData: r.body ? { mimeType: 'application/json', text: r.body } : undefined,
              },
              response: { headers: [], content: { mimeType: 'text/plain' } },
            })),
          },
        };
        const formData = new FormData();
        formData.append('file', new Blob([JSON.stringify(har)], { type: 'application/json' }), 'captured.har');
        formData.append('collection_name', colName);
        const res = await fetch('/api/discover/har', { method: 'POST', body: formData });
        const data = await res.json();
        window.closeModal();
        if (data.ok) alert(`Saved ${data.imported} requests to '${colName}'.`);
        else alert('Save failed: ' + data.error);
      }},
    ]);
  }

  // Auto-start recording after modal renders
  requestAnimationFrame(() => _startRecording());
}
