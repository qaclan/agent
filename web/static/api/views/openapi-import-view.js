export function showOpenApiImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Import from URL</label>
      <input id="openapi-url" type="url" class="input-sm" style="width:100%" placeholder="https://api.example.com/openapi.json">
    </div>
    <div style="text-align:center;color:var(--text-muted);margin:8px 0;font-size:12px;">— or —</div>
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload file (.json, .yaml)</label>
      <input id="openapi-file" type="file" accept=".json,.yaml,.yml" class="input-sm">
    </div>
    <div id="openapi-result" style="display:none;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:13px;"></div>`;

  window.showModal('Import OpenAPI / Swagger', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import', cls: 'btn-primary', action: _doImport },
  ]);

  async function _doImport() {
    const urlInput = document.getElementById('openapi-url');
    const fileInput = document.getElementById('openapi-file');
    const resultDiv = document.getElementById('openapi-result');

    let res;
    if (fileInput?.files[0]) {
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      res = await fetch('/api/discover/openapi', { method: 'POST', body: formData });
      res = await res.json();
    } else if (urlInput?.value.trim()) {
      res = await window.api('POST', '/discover/openapi', { url: urlInput.value.trim() });
    } else {
      alert('Provide a URL or upload a file.');
      return;
    }

    resultDiv.style.display = '';
    if (res.ok) {
      const cols = res.collections || [];
      resultDiv.innerHTML = `<strong>Imported ${res.imported} requests</strong> across ${cols.length} collections.<br>
        ${cols.map(c => `• ${c.name} (${c.count})`).join('<br>')}`;
    } else {
      resultDiv.innerHTML = `<span style="color:var(--danger)">${res.error}</span>`;
    }
  }
}
