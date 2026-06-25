import { showRequestReviewModal } from './request-review-modal.js';

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
      await window._alertDialog('No API requests captured. Make sure you interacted with the app and XHR/Fetch calls were made.');
      return;
    }
    showRequestReviewModal(res.requests, 'Recorded APIs');
  }

  function _cleanup() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }
}
