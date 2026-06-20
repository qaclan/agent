/**
 * API Section entry point.
 * Exposes window.__qaclanApi = { render(container) }
 * Loaded as <script type="module"> so it does not block the classic app.js.
 */

// Lazy import views to keep initial load fast
async function _loadViews() {
  const [
    { renderCollectionsView },
    { renderRequestEditor },
    { showDiscoverModal },
  ] = await Promise.all([
    import('./views/collections-view.js'),
    import('./views/request-editor-view.js'),
    import('./views/discover-modal.js'),
  ]);
  return { renderCollectionsView, renderRequestEditor, showDiscoverModal };
}

let _views = null;
async function _getViews() {
  if (!_views) _views = await _loadViews();
  return _views;
}

function renderApiPage(container) {
  container.innerHTML = '';

  const layout = document.createElement('div');
  layout.className = 'api-layout';

  // Sidebar
  const sidebar = document.createElement('div');
  sidebar.className = 'api-sidebar';
  sidebar.innerHTML = `
    <div class="api-sidebar-header">
      <span class="api-sidebar-title">API Testing</span>
      <button class="btn btn-xs btn-primary" id="api-discover-btn">+ Discover</button>
    </div>
    <div id="api-collections-panel"></div>`;
  layout.appendChild(sidebar);

  // Main content
  const main = document.createElement('div');
  main.className = 'api-main';
  main.id = 'api-main-content';
  main.innerHTML = '<div class="empty-state"><p>Select a request or collection to get started.</p></div>';
  layout.appendChild(main);

  container.appendChild(layout);

  // Load collections view into sidebar
  _getViews().then(({ renderCollectionsView, renderRequestEditor, showDiscoverModal }) => {
    renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId) => {
        renderRequestEditor(document.getElementById('api-main-content'), requestId);
      }
    );

    document.getElementById('api-discover-btn').onclick = () => showDiscoverModal();
  }).catch(err => {
    console.error('API section load error:', err);
    main.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Failed to load API module: ${err.message}</p></div>`;
  });
}

// Register global API
window.__qaclanApi = { render: renderApiPage };
