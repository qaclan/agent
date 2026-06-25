import { showRequestReviewModal } from './request-review-modal.js';

export function showPostmanImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload Postman Collection v2.1 (.json)</label>
      <input id="postman-file" type="file" accept=".json" class="input-sm">
    </div>
    <p id="postman-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import Postman Collection', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const fileInput = document.getElementById('postman-file');
    if (!fileInput?.files[0]) { await window._alertDialog('Please select a Postman collection file.'); return; }

    const status = document.getElementById('postman-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    let data;
    try {
      const res = await fetch('/api/discover/postman/preview', { method: 'POST', body: formData });
      data = await res.json();
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, fileInput.files[0].name.replace(/\.json$/i, ''));
  }
}

export function showBrunoImportView() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload .bru files (select multiple)</label>
      <input id="bruno-files" type="file" accept=".bru" multiple class="input-sm">
    </div>
    <p id="bruno-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import Bruno Files', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const fileInput = document.getElementById('bruno-files');
    if (!fileInput?.files.length) { await window._alertDialog('Please select .bru files.'); return; }

    const status = document.getElementById('bruno-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const formData = new FormData();
    for (const f of fileInput.files) formData.append('files', f);
    let data;
    try {
      const res = await fetch('/api/discover/bruno/preview', { method: 'POST', body: formData });
      data = await res.json();
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, 'Bruno Import');
  }
}
