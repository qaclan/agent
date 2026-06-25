import { showRequestReviewModal } from './request-review-modal.js';

export function showOpenApiImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Import from URL</label>
      <input id="openapi-url" type="url" class="input-sm" style="width:100%"
        placeholder="https://api.example.com/openapi.json">
    </div>
    <div style="text-align:center;color:var(--text-muted);margin:8px 0;font-size:12px;">— or —</div>
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload file (.json, .yaml)</label>
      <input id="openapi-file" type="file" accept=".json,.yaml,.yml" class="input-sm">
    </div>
    <p id="openapi-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import OpenAPI / Swagger', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const urlInput = document.getElementById('openapi-url');
    const fileInput = document.getElementById('openapi-file');
    const status = document.getElementById('openapi-status');

    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    let data;
    try {
      if (fileInput?.files[0]) {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        const res = await fetch('/api/discover/openapi/preview', { method: 'POST', body: formData });
        data = await res.json();
      } else if (urlInput?.value.trim()) {
        data = await window.api('POST', '/discover/openapi/preview', { url: urlInput.value.trim() });
      } else {
        if (status) status.style.display = 'none';
        await window._alertDialog('Provide a URL or upload a file.');
        return;
      }
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    const defaultName = fileInput?.files[0]
      ? fileInput.files[0].name.replace(/\.(json|yaml|yml)$/i, '')
      : 'OpenAPI Import';
    showRequestReviewModal(data.requests, defaultName);
  }
}
