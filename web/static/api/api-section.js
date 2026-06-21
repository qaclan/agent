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
      (requestId, defaultCollectionId) => {
        renderRequestEditor(document.getElementById('api-main-content'), requestId, defaultCollectionId);
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
