import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';

/**
 * renderRequestEditor(container, requestId, defaultCollectionId)
 * requestId: string|null (null = new request)
 * defaultCollectionId: string|null (pre-select collection when creating new)
 */
export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:20px">Loading...</div>';

  // Load existing request data if editing
  let existing = null;
  if (requestId) {
    const res = await window.api('GET', `/api-requests/${requestId}`);
    if (res.ok === false) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">${res.error}</p></div>`;
      return;
    }
    existing = res.request;
  }

  const r = existing || {};

  // Build editor shell
  container.innerHTML = '';
  const editor = document.createElement('div');
  editor.className = 'request-editor';

  // ── Name row ──
  const nameRow = document.createElement('div');
  nameRow.className = 'request-editor-name-row';
  nameRow.style.cssText = 'display:flex;gap:8px;align-items:center';
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'input-sm';
  nameInput.style.flex = '1';
  nameInput.placeholder = 'Request name';
  nameInput.value = r.name || '';
  nameRow.appendChild(nameInput);

  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-sm btn-ghost';
  saveBtn.textContent = 'Save';
  nameRow.appendChild(saveBtn);
  editor.appendChild(nameRow);

  // ── URL bar ──
  const urlBar = document.createElement('div');
  urlBar.className = 'request-editor-url-bar';

  const methodSelect = document.createElement('select');
  methodSelect.className = 'input-sm';
  methodSelect.style.width = '90px';
  ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    methodSelect.appendChild(opt);
  });
  methodSelect.value = r.method || 'GET';
  urlBar.appendChild(methodSelect);

  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'input-sm';
  urlInput.style.flex = '1';
  urlInput.placeholder = 'https://api.example.com/endpoint';
  urlInput.value = r.url || '';
  urlBar.appendChild(urlInput);

  const sendBtn = document.createElement('button');
  sendBtn.className = 'btn btn-sm btn-primary';
  sendBtn.textContent = 'Send';
  urlBar.appendChild(sendBtn);
  editor.appendChild(urlBar);

  // ── Tabbed sections ──
  const sections = ['Params', 'Headers', 'Body', 'Auth', 'Pre-Script', 'Post-Script', 'Assertions'];
  const tabBar = document.createElement('div');
  tabBar.className = 'response-tabs';
  const sectionContent = document.createElement('div');
  sectionContent.style.cssText = 'border:1px solid var(--border);border-top:none;border-radius:0 0 6px 6px;padding:12px;';
  editor.appendChild(tabBar);
  editor.appendChild(sectionContent);

  // Create component instances
  const paramsTable = createKeyValueTable({ placeholder: { key: 'Parameter', value: 'Value' } });
  paramsTable.setRows(r.params || []);

  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' } });
  headersTable.setRows(r.headers || []);

  const assertionBuilder = createAssertionBuilder();
  assertionBuilder.setAssertions(r.assertions || []);

  // Body section
  const bodySection = document.createElement('div');
  const bodyTypeSelect = document.createElement('select');
  bodyTypeSelect.className = 'input-sm';
  bodyTypeSelect.style.marginBottom = '8px';
  ['none', 'raw', 'form', 'graphql'].forEach(bt => {
    const opt = document.createElement('option');
    opt.value = bt;
    opt.textContent = bt;
    bodyTypeSelect.appendChild(opt);
  });
  bodyTypeSelect.value = r.body_type || 'none';
  const bodyTextarea = document.createElement('textarea');
  bodyTextarea.className = 'input-sm';
  bodyTextarea.style.cssText = 'width:100%;min-height:120px;font-family:var(--font-mono,monospace);font-size:12px;';
  bodyTextarea.value = r.body || '';
  bodySection.appendChild(bodyTypeSelect);
  bodySection.appendChild(bodyTextarea);

  // Auth section
  const authSection = document.createElement('div');
  const authTypeSelect = document.createElement('select');
  authTypeSelect.className = 'input-sm';
  authTypeSelect.style.marginBottom = '8px';
  ['none', 'bearer', 'basic', 'api_key', 'oauth2'].forEach(at => {
    const opt = document.createElement('option');
    opt.value = at;
    opt.textContent = at;
    authTypeSelect.appendChild(opt);
  });
  authTypeSelect.value = r.auth_type || 'none';
  const authConfigArea = document.createElement('textarea');
  authConfigArea.className = 'input-sm';
  authConfigArea.style.cssText = 'width:100%;min-height:80px;font-family:var(--font-mono,monospace);font-size:12px;';
  authConfigArea.placeholder = '{"token": "{{API_TOKEN}}"}';
  authConfigArea.value = typeof r.auth_config === 'object'
    ? JSON.stringify(r.auth_config, null, 2)
    : r.auth_config || '{}';
  authSection.appendChild(authTypeSelect);
  authSection.appendChild(authConfigArea);

  // Script sections
  function makeScriptSection(lang, code) {
    const div = document.createElement('div');
    const langSelect = document.createElement('select');
    langSelect.className = 'input-sm';
    langSelect.style.marginBottom = '8px';
    ['js', 'python'].forEach(l => {
      const opt = document.createElement('option');
      opt.value = l;
      opt.textContent = l === 'js' ? 'JavaScript' : 'Python';
      langSelect.appendChild(opt);
    });
    langSelect.value = lang || 'js';
    const textarea = document.createElement('textarea');
    textarea.className = 'input-sm';
    textarea.style.cssText = 'width:100%;min-height:100px;font-family:var(--font-mono,monospace);font-size:12px;';
    textarea.placeholder = 'qc.set("token", response.json().access_token)';
    textarea.value = code || '';
    div.appendChild(langSelect);
    div.appendChild(textarea);
    div._getLang = () => langSelect.value;
    div._getCode = () => textarea.value;
    return div;
  }

  const preScriptSection = makeScriptSection(r.pre_lang, r.pre_script);
  const postScriptSection = makeScriptSection(r.post_lang, r.post_script);

  const sectionMap = {
    'Params': paramsTable.el,
    'Headers': headersTable.el,
    'Body': bodySection,
    'Auth': authSection,
    'Pre-Script': preScriptSection,
    'Post-Script': postScriptSection,
    'Assertions': assertionBuilder.el,
  };

  let activeSection = 'Params';

  sections.forEach(name => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'response-tab' + (name === activeSection ? ' active' : '');
    tab.textContent = name;
    tab.onclick = () => {
      tabBar.querySelectorAll('.response-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeSection = name;
      sectionContent.innerHTML = '';
      sectionContent.appendChild(sectionMap[name]);
    };
    tabBar.appendChild(tab);
  });
  sectionContent.appendChild(sectionMap[activeSection]);

  // ── Response panel ──
  const responsePanel = createResponsePanel();
  editor.appendChild(responsePanel.el);

  container.appendChild(editor);

  // ── Wire up Send ──
  sendBtn.onclick = async () => {
    // Auto-save first if new
    let rid = requestId;
    if (!rid) {
      const saved = await _save();
      if (!saved) return;
      rid = saved;
    }
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';
    try {
      const res = await window.api('POST', `/api-requests/${rid}/send`, {});
      if (res.ok === false) {
        alert('Send error: ' + res.error);
      } else {
        responsePanel.show(res.result);
      }
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
  };

  // ── Wire up Save ──
  async function _save() {
    const payload = {
      name: nameInput.value.trim() || 'Unnamed Request',
      method: methodSelect.value,
      url: urlInput.value.trim(),
      params: paramsTable.getRows(),
      headers: headersTable.getRows(),
      body_type: bodyTypeSelect.value !== 'none' ? bodyTypeSelect.value : null,
      body: bodyTextarea.value || null,
      auth_type: authTypeSelect.value,
      auth_config: (() => { try { return JSON.parse(authConfigArea.value); } catch(e) { return {}; } })(),
      pre_lang: preScriptSection._getLang(),
      pre_script: preScriptSection._getCode() || null,
      post_lang: postScriptSection._getLang(),
      post_script: postScriptSection._getCode() || null,
      assertions: assertionBuilder.getAssertions(),
    };
    if (defaultCollectionId) payload.collection_id = defaultCollectionId;

    let res;
    if (requestId) {
      res = await window.api('PUT', `/api-requests/${requestId}`, payload);
    } else {
      res = await window.api('POST', '/api-requests', payload);
    }

    if (res.ok === false) {
      alert('Save failed: ' + res.error);
      return null;
    }
    return res.request?.id || requestId;
  }

  saveBtn.onclick = async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    try {
      const id = await _save();
      if (id) saveBtn.textContent = 'Saved ✓';
      else saveBtn.textContent = 'Save';
    } finally {
      saveBtn.disabled = false;
      setTimeout(() => { saveBtn.textContent = 'Save'; }, 2000);
    }
  };
}
