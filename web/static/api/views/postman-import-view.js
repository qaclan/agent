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
    showRequestReviewModal(data.requests, fileInput.files[0].name.replace(/\.json$/i, ''), null, {
      warnings: data.warnings,
      collection_vars: data.collection_vars,
      collection_auth: data.collection_auth,
    });
  }
}

export function showBrunoImportView() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload a collection folder (preserves subfolders + collection.bru)</label>
      <input id="bruno-folder" type="file" webkitdirectory directory multiple class="input-sm">
    </div>
    <div style="margin-bottom:12px;">
      <label class="form-label">…or select loose .bru files (no folder structure)</label>
      <input id="bruno-files" type="file" accept=".bru" multiple class="input-sm">
    </div>
    <p id="bruno-status" style="font-size:12px;color:var(--text-muted);margin-top:4px;display:none"></p>`;

  window.showModal('Import Bruno Files', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  async function _doPreview() {
    const folderInput = document.getElementById('bruno-folder');
    const fileInput = document.getElementById('bruno-files');
    const folderFiles = Array.from(folderInput?.files || []).filter(f => f.name.endsWith('.bru'));
    const looseFiles = Array.from(fileInput?.files || []);
    if (!folderFiles.length && !looseFiles.length) {
      await window._alertDialog('Please select a collection folder or .bru files.');
      return;
    }

    const status = document.getElementById('bruno-status');
    if (status) { status.style.display = ''; status.textContent = 'Parsing…'; }

    const formData = new FormData();
    // webkitRelativePath (e.g. "MyCollection/Auth/Login.bru") is stripped
    // to just the folder-relative part (drop the top-level picked-folder
    // name) so the backend's folder_path derivation lines up with how
    // qaclan represents collections, not the user's local folder name.
    for (const f of folderFiles) {
      const parts = f.webkitRelativePath.split('/').slice(1);
      formData.append('files', f, parts.join('/') || f.name);
    }
    for (const f of looseFiles) formData.append('files', f);

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
    showRequestReviewModal(data.requests, 'Bruno Import', null, {
      warnings: data.warnings,
      collection_vars: data.collection_vars,
      collection_auth: data.collection_auth,
    });
  }
}
