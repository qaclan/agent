function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showRecordApis() {
  const bodyHTML = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">
      Enter your app URL. The browser will open to this page so you can start interacting immediately.
    </p>
    <label class="form-label">Start URL</label>
    <input id="record-start-url" type="url" class="input-sm" style="width:100%"
      placeholder="https://your-app.com" autocomplete="url">
    <p id="record-url-error" style="color:var(--danger);font-size:12px;margin-top:4px;display:none">
      Enter a valid URL starting with http:// or https://
    </p>`;

  let _sessionId = null;
  let _pollTimer = null;
  let _startUrl = null;

  window.showModal('Record APIs', bodyHTML, [
    { label: 'Cancel', cls: 'btn-ghost', action: () => { _cleanup(); window.closeModal(); } },
    { label: 'Start Recording', cls: 'btn-primary', action: _onStart },
  ], null, 'md');

  requestAnimationFrame(() => {
    const input = document.getElementById('record-start-url');
    if (input) {
      input.focus();
      input.addEventListener('keydown', e => { if (e.key === 'Enter') _onStart(); });
    }
  });

  function _onStart() {
    const input = document.getElementById('record-start-url');
    const errEl = document.getElementById('record-url-error');
    const url = input ? input.value.trim() : '';
    if (!url || !/^https?:\/\/.+/.test(url)) {
      if (errEl) errEl.style.display = '';
      if (input) input.focus();
      return;
    }
    if (errEl) errEl.style.display = 'none';
    _startRecording(url);
  }

  async function _startRecording(url) {
    _startUrl = url;
    const modalBody = document.querySelector('.modal-body');
    if (modalBody) {
      modalBody.innerHTML = `
        <div class="record-status-badge recording">⏺ Recording</div>
        <p style="margin-top:10px;font-size:13px;color:var(--text-muted)">
          Interact with the browser window. XHR and Fetch requests are being captured.
        </p>
        <p style="font-size:12px;color:var(--text-muted);margin-top:4px">
          URL: <code>${_esc(url)}</code>
        </p>
        <p id="record-count" style="font-size:13px;margin-top:8px">Captured: <strong>0</strong> requests</p>`;
    }
    const stopBtn = document.querySelector('.modal-footer .btn-primary');
    if (stopBtn) {
      const newBtn = stopBtn.cloneNode(true);
      newBtn.textContent = 'Stop Recording';
      newBtn.addEventListener('click', _stopRecording);
      stopBtn.parentNode.replaceChild(newBtn, stopBtn);
    }

    const res = await window.api('POST', '/discover/record/start', { url });
    if (!res.ok) {
      const mb = document.querySelector('.modal-body');
      if (mb) mb.innerHTML = `<p style="color:var(--danger)">Failed to start: ${_esc(res.error)}</p>`;
      return;
    }
    _sessionId = res.session_id;
    _pollTimer = setInterval(_pollStatus, 3000);
  }

  async function _pollStatus() {
    if (!_sessionId) return;
    const res = await window.api('GET', `/discover/record/status?session_id=${_sessionId}`);
    if (!res.ok) return;
    if (res.status === 'stopped') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      const badge = document.querySelector('.record-status-badge');
      if (badge) { badge.className = 'record-status-badge stopped'; badge.textContent = '● Stopped (browser closed)'; }
    }
  }

  async function _stopRecording() {
    _cleanup();
    if (!_sessionId) { window.closeModal(); return; }

    const sid = _sessionId;
    _sessionId = null;
    const res = await window.api('POST', '/discover/record/stop', { session_id: sid });
    window.closeModal();

    if (!res.ok || !res.requests?.length) {
      alert('No API requests captured. Make sure you interacted with the app and XHR/Fetch calls were made.');
      return;
    }
    _showCapturedResults(res.requests, _startUrl);
  }

  function _cleanup() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  function _showCapturedResults(requests, startUrl) {
    let startHostname = '';
    try { startHostname = new URL(startUrl || '').hostname; } catch {}

    let hidingThirdParty = !!startHostname;

    function _hostname(url) {
      try { return new URL(url).hostname; } catch { return ''; }
    }

    const indexedRequests = requests.map((r, i) => ({ ...r, _origIdx: i }));

    function _visible() {
      if (!hidingThirdParty || !startHostname) return indexedRequests;
      return indexedRequests.filter(r => _hostname(r.url) === startHostname);
    }

    function _renderList(listEl) {
      const vis = _visible();
      listEl.innerHTML = vis.length
        ? vis.map(r => `
            <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);font-size:12px;">
              <input type="checkbox" id="cap-${r._origIdx}" checked>
              <label for="cap-${r._origIdx}" style="flex:1;cursor:pointer;word-break:break-all;">
                <span class="method-badge method-${_esc(r.method)}" style="font-size:10px;padding:1px 5px;">${_esc(r.method)}</span>
                ${_esc(r.url.replace(/\?.*/, ''))}
              </label>
            </div>`).join('')
        : '<p style="padding:12px;font-size:12px;color:var(--text-muted);margin:0">No requests match the current filter.</p>';
    }

    const thirdPartyCount = startHostname
      ? indexedRequests.filter(r => _hostname(r.url) !== startHostname).length
      : 0;

    const modalBodyHTML = `
      <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">
        ${requests.length} XHR/Fetch request${requests.length !== 1 ? 's' : ''} captured. Select which to save:
      </p>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
        <div style="display:flex;gap:8px;">
          <button type="button" class="btn-ghost" id="cap-all" style="font-size:11px;padding:2px 8px;">All</button>
          <button type="button" class="btn-ghost" id="cap-none" style="font-size:11px;padding:2px 8px;">None</button>
        </div>
        ${thirdPartyCount > 0 ? `
        <label style="display:flex;align-items:center;gap:5px;font-size:12px;cursor:pointer;color:var(--text-muted);">
          <input type="checkbox" id="hide-3p" ${hidingThirdParty ? 'checked' : ''}>
          Hide third-party (${thirdPartyCount})
        </label>` : ''}
      </div>
      <div id="captured-list" style="max-height:260px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;"></div>
      <div style="margin-top:10px;">
        <label class="form-label">Save to collection</label>
        <input id="capture-col-name" type="text" class="input-sm" style="width:100%" value="Recorded APIs">
      </div>
      <label style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:12px;cursor:pointer;">
        <input type="checkbox" id="capture-include-docs" checked>
        Include in API Documentation
      </label>`;

    window.showModal('Save Captured Requests', modalBodyHTML, [
      { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
      { label: 'Save Selected', cls: 'btn-primary', action: async () => {
        const colName = document.getElementById('capture-col-name')?.value.trim() || 'Recorded APIs';
        const selected = requests.filter((_, i) => document.getElementById(`cap-${i}`)?.checked);
        if (!selected.length) { alert('No requests selected.'); return; }

        const includeInDocs = document.getElementById('capture-include-docs')?.checked ? 1 : 0;
        const data = await window.api('POST', '/discover/save-requests', {
          requests: selected,
          collection_name: colName,
          include_in_docs: includeInDocs,
        });
        window.closeModal();
        if (data.ok) {
          if (window.__qaclanApi?.refresh) window.__qaclanApi.refresh();
          alert(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${colName}'.`);
        } else {
          alert('Save failed: ' + data.error);
        }
      }},
    ]);

    requestAnimationFrame(() => {
      const listEl = document.getElementById('captured-list');
      if (listEl) _renderList(listEl);

      document.getElementById('hide-3p')?.addEventListener('change', e => {
        hidingThirdParty = e.target.checked;
        if (listEl) _renderList(listEl);
      });
      document.getElementById('cap-all')?.addEventListener('click', () =>
        listEl?.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = true));
      document.getElementById('cap-none')?.addEventListener('click', () =>
        listEl?.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = false));
    });
  }
}
