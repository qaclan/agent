export function showPostmanImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload Postman Collection v2.1 (.json)</label>
      <input id="postman-file" type="file" accept=".json" class="input-sm">
    </div>
    <div id="postman-result" style="display:none;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:13px;"></div>`;

  window.showModal('Import Postman Collection', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import', cls: 'btn-primary', action: _doImport },
  ]);

  async function _doImport() {
    const fileInput = document.getElementById('postman-file');
    if (!fileInput?.files[0]) { alert('Please select a Postman collection file.'); return; }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    const res = await fetch('/api/discover/postman', { method: 'POST', body: formData });
    const data = await res.json();

    const resultDiv = document.getElementById('postman-result');
    resultDiv.style.display = '';
    if (data.ok) {
      resultDiv.innerHTML = `<strong>Imported ${data.imported} requests.</strong>`;
      setTimeout(() => window.closeModal(), 1500);
    } else {
      resultDiv.innerHTML = `<span style="color:var(--danger)">${data.error}</span>`;
    }
  }
}

export function showBrunoImportView() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload .bru files (select multiple)</label>
      <input id="bruno-files" type="file" accept=".bru" multiple class="input-sm">
    </div>
    <div id="bruno-result" style="display:none;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:13px;"></div>`;

  window.showModal('Import Bruno Files', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import', cls: 'btn-primary', action: _doImport },
  ]);

  async function _doImport() {
    const fileInput = document.getElementById('bruno-files');
    if (!fileInput?.files.length) { alert('Please select .bru files.'); return; }

    const formData = new FormData();
    for (const f of fileInput.files) formData.append('files', f);

    const res = await fetch('/api/discover/bruno', { method: 'POST', body: formData });
    const data = await res.json();

    const resultDiv = document.getElementById('bruno-result');
    resultDiv.style.display = '';
    if (data.ok) {
      resultDiv.innerHTML = `<strong>Imported ${data.imported} requests.</strong>`;
      setTimeout(() => window.closeModal(), 1500);
    } else {
      resultDiv.innerHTML = `<span style="color:var(--danger)">${data.error}</span>`;
    }
  }
}
