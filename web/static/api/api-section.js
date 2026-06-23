/**
 * API Section entry point.
 * Exposes window.__qaclanApi = { render(container) }
 */

if (!window.api) {
  window.api = async function api(method, path, body = null) {
    try {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const res = await fetch('/api' + path, opts);
      const data = await res.json();
      return data;
    } catch (e) {
      return { ok: false, error: e.message };
    }
  };
}

if (!window._qcDialog) {
  window._qcDialog = function(opts) {
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.55);backdrop-filter:blur(2px);display:flex;align-items:center;justify-content:center;';

      const box = document.createElement('div');
      box.style.cssText = 'background:var(--bg-elevated);border:1px solid var(--border-strong);border-radius:10px;padding:20px 24px;max-width:400px;width:90%;box-shadow:var(--shadow-lg);';

      const msgEl = document.createElement('p');
      msgEl.style.cssText = 'margin:0 0 4px;font-size:14px;font-weight:600;color:var(--text-primary);';
      msgEl.textContent = opts.message;
      box.appendChild(msgEl);

      if (opts.detail) {
        const d = document.createElement('p');
        d.style.cssText = 'margin:0 0 12px;font-size:12px;color:var(--text-muted);line-height:1.5;';
        d.textContent = opts.detail;
        box.appendChild(d);
      }

      let inputEl;
      if (opts.type === 'prompt') {
        inputEl = document.createElement('input');
        inputEl.type = 'text';
        inputEl.value = opts.defaultValue || '';
        inputEl.style.cssText = 'width:100%;box-sizing:border-box;margin-top:8px;margin-bottom:4px;padding:7px 10px;font-size:13px;border:1px solid var(--border-strong);border-radius:6px;background:var(--bg-panel);color:var(--text-primary);outline:none;';
        box.appendChild(inputEl);
      }

      const btns = document.createElement('div');
      btns.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:16px;';

      function _close(val) { document.body.removeChild(overlay); resolve(val); }

      if (opts.type !== 'alert') {
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button'; cancelBtn.className = 'btn btn-sm btn-ghost';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.onclick = () => _close(opts.type === 'prompt' ? null : false);
        btns.appendChild(cancelBtn);
      }

      const okBtn = document.createElement('button');
      okBtn.type = 'button';
      okBtn.className = opts.confirmCls || 'btn btn-sm btn-primary';
      okBtn.textContent = opts.confirmLabel || (opts.type === 'alert' ? 'OK' : opts.type === 'prompt' ? 'OK' : 'Confirm');
      okBtn.onclick = () => {
        if (opts.type === 'confirm') _close(true);
        else if (opts.type === 'prompt') _close(inputEl?.value.trim() || null);
        else _close(undefined);
      };
      btns.appendChild(okBtn);

      box.appendChild(btns);
      overlay.appendChild(box);
      document.body.appendChild(overlay);

      if (opts.type === 'alert') {
        overlay.onclick = e => { if (e.target === overlay) _close(undefined); };
      }
      if (opts.type === 'prompt' && inputEl) {
        setTimeout(() => { inputEl.focus(); inputEl.select(); }, 10);
        inputEl.onkeydown = e => { if (e.key === 'Enter') okBtn.click(); if (e.key === 'Escape') btns.querySelector('.btn-ghost')?.click(); };
      } else {
        setTimeout(() => okBtn.focus(), 10);
      }
    });
  };

  window._alertDialog  = msg => window._qcDialog({ type: 'alert', message: msg });
  window._confirmDialog = (msg, detail, confirmLabel, confirmCls) =>
    window._qcDialog({ type: 'confirm', message: msg, detail, confirmLabel, confirmCls });
  window._promptDialog = (msg, defaultValue) =>
    window._qcDialog({ type: 'prompt', message: msg, defaultValue });

  window._toast = function(msg, duration = 2000) {
    const t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:10000;background:var(--success-bg);border:1px solid var(--success-border);color:var(--success);border-radius:6px;padding:8px 14px;font-size:12px;font-weight:500;box-shadow:var(--shadow-md);pointer-events:none;transition:opacity .3s;';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 320); }, duration);
  };
}

async function _loadViews() {
  const [
    { renderCollectionsView },
    { renderRequestEditor },
    { showDiscoverModal },
    { renderDocsView },
  ] = await Promise.all([
    import('./views/collections-view.js'),
    import('./views/request-editor-view.js'),
    import('./views/discover-modal.js'),
    import('./views/docs-view.js'),
  ]);
  return { renderCollectionsView, renderRequestEditor, showDiscoverModal, renderDocsView };
}

let _views = null;
async function _getViews() {
  if (!_views) _views = await _loadViews();
  return _views;
}

function renderApiPage(container) {
  container.innerHTML = '';

  // Top tab bar: Collections | API Docs
  const topBar = document.createElement('div');
  topBar.style.cssText = 'display:flex;align-items:center;gap:0;border-bottom:1px solid var(--border);padding:0 14px;background:var(--surface-1,var(--bg));flex-shrink:0;';

  const tabCollections = document.createElement('button');
  tabCollections.type = 'button';
  tabCollections.className = 'req-tab active';
  tabCollections.textContent = 'Collections';

  const tabDocs = document.createElement('button');
  tabDocs.type = 'button';
  tabDocs.className = 'req-tab';
  tabDocs.textContent = 'API Docs';

  topBar.appendChild(tabCollections);
  topBar.appendChild(tabDocs);

  const pageWrap = document.createElement('div');
  pageWrap.style.cssText = 'display:flex;flex-direction:column;height:100%;overflow:hidden;';
  pageWrap.appendChild(topBar);

  // Collections panel (api-layout with sidebar + main)
  const collectionsPanel = document.createElement('div');
  collectionsPanel.style.cssText = 'flex:1;overflow:hidden;display:flex;';
  collectionsPanel.innerHTML = `
    <div class="api-layout" style="flex:1;overflow:hidden;">
      <div class="api-sidebar">
        <div class="api-sidebar-header">
          <span class="api-sidebar-title">Collections</span>
          <button class="btn btn-xs btn-primary" id="api-discover-btn">+ Discover</button>
        </div>
        <div id="api-collections-panel"></div>
      </div>
      <div class="api-main" id="api-main-content">
        <div class="empty-state"><p>Select a request or collection to get started.</p></div>
      </div>
    </div>`;

  // Docs panel
  const docsPanel = document.createElement('div');
  docsPanel.style.cssText = 'flex:1;overflow:hidden;display:none;';

  pageWrap.appendChild(collectionsPanel);
  pageWrap.appendChild(docsPanel);
  container.appendChild(pageWrap);

  function _switchTab(tab) {
    if (tab === 'collections') {
      tabCollections.classList.add('active');
      tabDocs.classList.remove('active');
      collectionsPanel.style.display = 'flex';
      docsPanel.style.display = 'none';
    } else {
      tabDocs.classList.add('active');
      tabCollections.classList.remove('active');
      collectionsPanel.style.display = 'none';
      docsPanel.style.display = 'flex';
      // Re-render docs each time tab is opened so it picks up new recordings
      _getViews().then(({ renderDocsView }) => renderDocsView(docsPanel))
        .catch(err => {
          console.error('Docs view load error:', err);
          docsPanel.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Failed to load docs: ${err.message}</p></div>`;
        });
    }
  }

  tabCollections.onclick = () => _switchTab('collections');
  tabDocs.onclick = () => _switchTab('docs');

  // Wire collections view
  _getViews().then(({ renderCollectionsView, renderRequestEditor, showDiscoverModal }) => {
    renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId, defaultCollectionId, collectionId, collectionEnvName) => {
        renderRequestEditor(
          document.getElementById('api-main-content'),
          requestId,
          defaultCollectionId,
          collectionId,
          collectionEnvName,
        );
      }
    );
    document.getElementById('api-discover-btn').onclick = () => showDiscoverModal();
  }).catch(err => {
    console.error('API section load error:', err);
    document.getElementById('api-main-content').innerHTML =
      `<div class="empty-state"><p style="color:var(--danger)">Failed to load API module: ${err.message}</p></div>`;
  });
}

window.__qaclanApi = { render: renderApiPage };
