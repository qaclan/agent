import { showRequestReviewModal } from './request-review-modal.js';

export function showCurlImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Paste one or more curl commands</label>
      <textarea id="curl-input" class="input-sm" rows="10" style="width:100%;font-family:var(--font-mono);font-size:12px;"
        placeholder="curl -X POST https://api.example.com/login -H 'Content-Type: application/json' --data-raw '{&quot;user&quot;:&quot;a&quot;}'"></textarea>
    </div>
    <p id="curl-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import cURL', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const input = document.getElementById('curl-input');
    const text = input?.value.trim();
    if (!text) { await window._alertDialog('Please paste at least one curl command.'); return; }

    const status = document.getElementById('curl-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const data = await window.api('POST', '/discover/curl/preview', { curl: text });

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, 'Imported cURL');
  }
}
