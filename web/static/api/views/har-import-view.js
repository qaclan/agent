import { showRequestReviewModal } from './request-review-modal.js';

export function showHarImport() {
  const body = `
    <div id="har-drop-zone" style="border:2px dashed var(--border);border-radius:8px;padding:32px;text-align:center;cursor:pointer;">
      <p style="margin:0;color:var(--text-muted)">Drag & drop .har file here, or <strong>click to browse</strong></p>
      <input type="file" id="har-file-input" accept=".har,application/json" style="display:none">
    </div>
    <p id="har-status" style="font-size:12px;color:var(--text-muted);margin-top:8px;display:none"></p>`;

  window.showModal('Import HAR', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Preview Requests', cls: 'btn-primary', action: _doPreview },
  ]);

  let _selectedFile = null;

  requestAnimationFrame(() => {
    const dropZone = document.getElementById('har-drop-zone');
    const fileInput = document.getElementById('har-file-input');

    dropZone.onclick = () => fileInput.click();
    fileInput.onchange = e => e.target.files[0] && _setFile(e.target.files[0]);
    dropZone.ondragover = e => { e.preventDefault(); dropZone.style.borderColor = 'var(--primary)'; };
    dropZone.ondragleave = () => { dropZone.style.borderColor = 'var(--border)'; };
    dropZone.ondrop = e => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border)';
      if (e.dataTransfer.files[0]) _setFile(e.dataTransfer.files[0]);
    };
  });

  function _setFile(file) {
    _selectedFile = file;
    const status = document.getElementById('har-status');
    if (status) { status.style.display = ''; status.textContent = `Selected: ${file.name}`; }
  }

  async function _doPreview() {
    if (!_selectedFile) { await window._alertDialog('Please select a HAR file first.'); return; }

    const status = document.getElementById('har-status');
    if (status) { status.textContent = 'Parsing…'; status.style.display = ''; }

    const formData = new FormData();
    formData.append('file', _selectedFile);
    let data;
    try {
      const res = await fetch('/api/discover/har/preview', { method: 'POST', body: formData });
      data = await res.json();
    } catch (e) {
      await window._alertDialog('Network error: ' + e.message);
      return;
    }

    if (!data.ok) { await window._alertDialog('Parse failed: ' + data.error); return; }

    window.closeModal();
    showRequestReviewModal(data.requests, _selectedFile.name.replace(/\.har$/i, ''));
  }
}
