/**
 * renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection)
 * container: DOM element to render into
 * onSelectRequest: (requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId) => void
 * defaultFolderId: string|null — which folder a "+ New Request" click was made from
 */
export function renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading...</div>';

  let _runningByColId = {};
  let _activeRequestId = null; // re-applied to the matching row after every reload()
  const _scrollParent = container.closest('.api-sidebar') || container;
  let _savedScrollTop = 0; // restored after reload() and after each collection's async tree load

  // Fed by the shared active-runs-tracker in api-section.js — this view no
  // longer polls the RUNNING endpoint itself, since the top-bar run-status
  // chip already polls it once for the whole page.
  function updateRunningRuns(runs) {
    const fresh = {};
    (runs || []).forEach(r => { if (r.collection_id) fresh[r.collection_id] = r.id; });
    const changed = JSON.stringify(fresh) !== JSON.stringify(_runningByColId);
    _runningByColId = fresh;
    if (changed) _updateRunningDots();
  }

  function _updateRunningDots() {
    document.querySelectorAll('[data-col-dot]').forEach(dot => {
      const colId = dot.dataset.colDot;
      dot.style.display = _runningByColId[colId] ? '' : 'none';
    });
  }

  async function reload() {
    _savedScrollTop = _scrollParent.scrollTop;
    const res = await window.api('GET', '/collections');
    const collections = res.collections || [];
    container.innerHTML = '';

    if (!document.getElementById('cdot-style')) {
      const st = document.createElement('style');
      st.id = 'cdot-style';
      st.textContent = '@keyframes cdot-pulse{0%,100%{opacity:1}50%{opacity:.3}}';
      document.head.appendChild(st);
    }

    if (!collections.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted text-sm';
      empty.style.cssText = 'padding:10px 14px;';
      empty.textContent = 'No collections yet.';
      container.appendChild(empty);
      _appendNewCollectionButton();
      return;
    }

    collections.forEach(col => container.appendChild(_renderCollectionSection(col)));
    _appendNewCollectionButton();
    _wireCollectionOrderDrag();
    _reapplyActiveRow();
    _scrollParent.scrollTop = _savedScrollTop;
    _updateRunningDots();
  }

  function _appendNewCollectionButton() {
    const newColBtn = document.createElement('div');
    newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
    newColBtn.textContent = '+ New Collection';
    newColBtn.onclick = _createCollection;
    container.appendChild(newColBtn);
  }

  // ---- Collection section (header + tree) ----

  function _renderCollectionSection(col) {
    const section = document.createElement('div');
    section.className = 'api-collection-section';
    section.dataset.collectionId = col.id;

    const header = document.createElement('div');
    header.className = 'api-collection-item api-collection-header';
    header.draggable = true;

    const leftSide = document.createElement('span');
    leftSide.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1;min-width:0;';
    leftSide.innerHTML = `
      <span class="api-drag-handle">⠿</span>
      <span data-col-dot="${_esc(col.id)}" style="display:none;width:7px;height:7px;border-radius:50%;
        background:var(--warning,#f59e0b);flex-shrink:0;animation:cdot-pulse 1s infinite"></span>
      <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(col.name)}</strong>
      <span class="text-muted text-sm" style="flex-shrink:0;">(${col.request_count})</span>`;
    leftSide.onclick = async (e) => {
      e.stopPropagation();
      if (onSelectCollection) {
        const runId = _runningByColId[col.id] || null;
        await onSelectCollection(col, runId);
      }
    };
    header.appendChild(leftSide);

    const rightSide = document.createElement('span');
    rightSide.style.cssText = 'display:flex;gap:2px;align-items:center;';

    const runBtn = document.createElement('button');
    runBtn.className = 'btn btn-xs btn-ghost';
    runBtn.title = 'Run collection';
    runBtn.textContent = '▶';
    runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name, col.env_name); };
    rightSide.appendChild(runBtn);

    const menuWrap = document.createElement('span');
    menuWrap.style.cssText = 'position:relative;';
    const menuBtn = document.createElement('button');
    menuBtn.className = 'btn btn-xs btn-ghost';
    menuBtn.title = 'More';
    menuBtn.textContent = '⋯';
    menuWrap.appendChild(menuBtn);

    const menuDropdown = document.createElement('div');
    menuDropdown.className = 'project-dropdown hidden';
    menuDropdown.style.cssText = 'right:0;min-width:170px;';
    menuDropdown.innerHTML = `
      <div class="project-dropdown-item" data-action="new-request">+ New Request</div>
      <div class="project-dropdown-item" data-action="new-folder">+ New Folder</div>
      <div class="project-dropdown-divider"></div>
      <div class="project-dropdown-item" data-action="export-postman">Export as Postman</div>
      <div class="project-dropdown-item" data-action="export-bruno">Export as Bruno</div>
      <div class="project-dropdown-divider"></div>
      <div class="project-dropdown-item" data-action="delete" style="color:var(--danger,#e53e3e)">Delete Collection</div>`;
    menuWrap.appendChild(menuDropdown);
    rightSide.appendChild(menuWrap);

    function _closeMenu() {
      menuDropdown.classList.add('hidden');
      document.removeEventListener('click', _onMenuDocClick, true);
    }
    function _onMenuDocClick(e) {
      if (!menuWrap.contains(e.target)) _closeMenu();
    }
    menuBtn.onclick = (e) => {
      e.stopPropagation();
      const willOpen = menuDropdown.classList.contains('hidden');
      if (willOpen) {
        menuDropdown.classList.remove('hidden');
        document.addEventListener('click', _onMenuDocClick, true);
      } else {
        _closeMenu();
      }
    };
    menuDropdown.onclick = async (e) => {
      e.stopPropagation();
      const action = e.target.closest('[data-action]')?.dataset.action;
      if (!action) return;
      _closeMenu();
      if (action === 'new-request') await _triggerNewRequest();
      else if (action === 'new-folder') await _triggerNewFolder();
      else if (action === 'export-postman') await _exportCollection(col.id, col.name, 'postman');
      else if (action === 'export-bruno') await _exportCollection(col.id, col.name, 'bruno');
      else if (action === 'delete') _deleteCollection(col.id, col.name);
    };

    const expandBtn = document.createElement('button');
    expandBtn.className = 'btn btn-xs btn-ghost';
    expandBtn.textContent = '▾';
    rightSide.appendChild(expandBtn);
    header.appendChild(rightSide);

    section.appendChild(header);

    const treeRoot = document.createElement('div');
    treeRoot.className = 'api-tree-root';
    let expanded = true;

    function _toggleExpand() {
      expanded = !expanded;
      treeRoot.style.display = expanded ? '' : 'none';
      expandBtn.textContent = expanded ? '▾' : '▸';
    }
    header.onclick = (e) => {
      if (rightSide.contains(e.target)) return;
      if (leftSide.contains(e.target)) return;
      _toggleExpand();
    };
    expandBtn.onclick = (e) => { e.stopPropagation(); _toggleExpand(); };

    section.appendChild(treeRoot);

    let allFolders = [];
    let allRequests = [];
    const rerender = () => _renderTreeLevel(treeRoot, col, null, allFolders, allRequests);

    async function _triggerNewRequest() {
      const proceed = await onSelectRequest(null, col.id, col.id, col.env_name, null);
      if (proceed === false) return;
      container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
      _activeRequestId = null;
    }

    async function _triggerNewFolder() {
      const name = await window._promptDialog('Folder name:');
      if (!name) return;
      const res = await window.api('POST', `/collections/${col.id}/folders`, {
        name: name.trim(), parent_folder_id: null,
      });
      if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
      allFolders.push(res.folder);
      rerender();
    }

    window.api('GET', `/collections/${col.id}/tree`).then(treeRes => {
      allFolders = treeRes.folders || [];
      allRequests = treeRes.requests || [];
      rerender();
      _wireCollectionTreeDrag(treeRoot, col, allFolders, allRequests, rerender);
      _reapplyActiveRow();
      _scrollParent.scrollTop = _savedScrollTop;
    });

    return section;
  }

  // ---- Tree rendering (recursive) ----

  function _renderTreeLevel(containerEl, col, parentFolderId, allFolders, allRequests) {
    containerEl.dataset.parentFolderId = parentFolderId || '';
    containerEl.innerHTML = '';

    const childFolders = allFolders.filter(f => (f.parent_folder_id || null) === parentFolderId);
    const childRequests = allRequests.filter(r => (r.folder_id || null) === parentFolderId);
    const nodes = [
      ...childFolders.map(f => ({ type: 'folder', order_index: f.order_index, data: f })),
      ...childRequests.map(r => ({ type: 'request', order_index: r.order_index, data: r })),
    ].sort((a, b) => a.order_index - b.order_index);

    nodes.forEach(node => {
      containerEl.appendChild(node.type === 'folder'
        ? _renderFolderNode(col, node.data, allFolders, allRequests)
        : _renderRequestNode(col, node.data, parentFolderId));
    });

    if (parentFolderId) {
      containerEl.appendChild(_renderNewRequestRow(col, parentFolderId));
      containerEl.appendChild(_renderNewFolderRow(col, parentFolderId, allFolders, allRequests, containerEl));
    }
  }

  function _renderFolderNode(col, folder, allFolders, allRequests) {
    // Returns a DocumentFragment of two siblings — [row, childrenEl] — rather than a
    // wrapping <div>. This matters for drag-and-drop: dragEl.parentElement must be the
    // shared level container (containerEl) for BOTH folder rows and request rows, so the
    // "same level = plain reorder" check in _wireCollectionTreeDrag works uniformly. A
    // wrapping div would put a folder row one level deeper in the DOM than a request row.
    const row = document.createElement('div');
    row.className = 'api-folder-item';
    row.draggable = true;
    row.dataset.nodeType = 'folder';
    row.dataset.nodeId = folder.id;
    row.innerHTML = `
      <span class="api-drag-handle">⠿</span>
      <span class="api-folder-toggle">▾</span>
      <span class="api-folder-name">${_esc(folder.name)}</span>`;

    const actions = document.createElement('span');
    actions.className = 'api-folder-actions';

    const renameBtn = document.createElement('button');
    renameBtn.className = 'btn btn-xs btn-ghost';
    renameBtn.title = 'Rename folder';
    renameBtn.textContent = '✎';
    renameBtn.onclick = async (e) => { e.stopPropagation(); await _renameFolder(folder); };
    actions.appendChild(renameBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-xs btn-ghost';
    delBtn.title = 'Delete folder';
    delBtn.style.color = 'var(--danger,#e53e3e)';
    delBtn.textContent = '🗑';
    delBtn.onclick = async (e) => { e.stopPropagation(); await _deleteFolder(folder); };
    actions.appendChild(delBtn);

    row.appendChild(actions);

    const childrenEl = document.createElement('div');
    childrenEl.className = 'api-folder-children';

    let expanded = true;
    const toggle = row.querySelector('.api-folder-toggle');
    row.onclick = (e) => {
      if (actions.contains(e.target)) return;
      expanded = !expanded;
      childrenEl.style.display = expanded ? '' : 'none';
      toggle.textContent = expanded ? '▾' : '▸';
    };

    _renderTreeLevel(childrenEl, col, folder.id, allFolders, allRequests);

    const frag = document.createDocumentFragment();
    frag.appendChild(row);
    frag.appendChild(childrenEl);
    return frag;
  }

  // Discovery/import-generated names are "METHOD /path" — the method is
  // already shown by the colored badge, so strip a matching leading prefix
  // to avoid showing it twice. Leaves custom (renamed) names untouched.
  function _displayReqName(req) {
    const name = req.name || '';
    const prefix = `${req.method || ''} `;
    return name.toUpperCase().startsWith(prefix.toUpperCase()) ? name.slice(prefix.length) : name;
  }

  function _renderRequestNode(col, req, parentFolderId) {
    const item = document.createElement('div');
    item.className = 'api-request-item';
    item.draggable = true;
    item.dataset.nodeType = 'request';
    item.dataset.nodeId = req.id;
    item.innerHTML = `
      <span class="api-drag-handle">⠿</span>
      <span class="method-badge method-${req.method}">${req.method}</span>
      <span>${_esc(_displayReqName(req))}</span>
      <span data-req-dot="${_esc(req.id)}" class="req-unsaved-dot" style="display:none" title="Unsaved changes"></span>`;

    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-from-col-btn';
    removeBtn.title = 'Remove from collection';
    removeBtn.innerHTML = '&#x2715;';
    removeBtn.onclick = async (e) => {
      e.stopPropagation();
      const confirmed = await window._confirmDialog(
        'Remove from collection?',
        `"${req.name}" will be removed from this collection but not deleted.`,
        'Remove'
      );
      if (!confirmed) return;
      const res = await window.api('PATCH', `/api-requests/${req.id}`, { collection_id: null, folder_id: null });
      if (res.ok === false) {
        await window._alertDialog('Error: ' + (res.error || 'unknown error'));
        return;
      }
      item.remove();
    };
    item.appendChild(removeBtn);

    item.onclick = async (e) => {
      if (removeBtn.contains(e.target)) return;
      if (item.classList.contains('active')) return;
      const proceed = await onSelectRequest(req.id, null, col.id, col.env_name, parentFolderId);
      if (proceed === false) return; // caller declined (unsaved-changes confirm)
      container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      _activeRequestId = req.id;
    };

    return item;
  }

  function _renderNewRequestRow(col, parentFolderId) {
    const row = document.createElement('div');
    row.className = 'api-request-item api-new-item-row';
    row.innerHTML = `<span style="color:var(--text-muted)">+ New Request</span>`;
    row.onclick = async () => {
      const proceed = await onSelectRequest(null, col.id, col.id, col.env_name, parentFolderId);
      if (proceed === false) return;
      container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
      row.classList.add('active');
      _activeRequestId = null;
    };
    return row;
  }

  // Re-applies the `.active` highlight to whichever request row matches
  // the last-selected request id — reload() rebuilds the tree from scratch,
  // so without this the selection highlight would disappear on every save.
  function _reapplyActiveRow() {
    if (!_activeRequestId) return;
    container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
    const row = container.querySelector(`.api-request-item[data-node-id="${_activeRequestId}"]`);
    if (row) row.classList.add('active');
  }

  function _renderNewFolderRow(col, parentFolderId, allFolders, allRequests, containerEl) {
    const row = document.createElement('div');
    row.className = 'api-request-item api-new-item-row';
    row.innerHTML = `<span style="color:var(--text-muted)">+ New Folder</span>`;
    row.onclick = async () => {
      const name = await window._promptDialog('Folder name:');
      if (!name) return;
      const res = await window.api('POST', `/collections/${col.id}/folders`, {
        name: name.trim(), parent_folder_id: parentFolderId,
      });
      if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
      allFolders.push(res.folder);
      _renderTreeLevel(containerEl, col, parentFolderId, allFolders, allRequests);
    };
    return row;
  }

  async function _renameFolder(folder) {
    const name = await window._promptDialog('Rename folder:', folder.name);
    if (!name || name.trim() === folder.name) return;
    const res = await window.api('PATCH', `/api-folders/${folder.id}`, { name: name.trim() });
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  async function _deleteFolder(folder) {
    const confirmed = await window._confirmDialog(
      `Delete '${folder.name}'?`,
      'This folder and everything inside it (sub-folders and requests) will be permanently deleted.',
      'Delete', 'btn btn-sm btn-danger'
    );
    if (!confirmed) return;
    const res = await window.api('DELETE', `/api-folders/${folder.id}`);
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  // ---- Drag-and-drop: folders + requests within one collection ----
  // One delegated listener per collection (attached to that collection's treeRoot),
  // not one per level — avoids nested-listener event-bubbling conflicts entirely.

  function _isDescendant(folderId, allFolders, candidateId) {
    let cursor = allFolders.find(f => f.id === candidateId);
    while (cursor) {
      if (cursor.id === folderId) return true;
      cursor = allFolders.find(f => f.id === cursor.parent_folder_id);
    }
    return false;
  }

  function _wireCollectionTreeDrag(treeRoot, col, allFolders, allRequests, rerender) {
    let dragEl = null;
    let hoverFolderRow = null;

    treeRoot.addEventListener('dragstart', e => {
      const row = e.target.closest('[data-node-type]');
      if (!row) return;
      dragEl = row;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    treeRoot.addEventListener('dragover', e => {
      if (!dragEl) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';

      if (hoverFolderRow) { hoverFolderRow.classList.remove('drop-target-folder'); hoverFolderRow = null; }

      const targetRow = e.target.closest('[data-node-type]');
      if (!targetRow || targetRow === dragEl) return;

      const rect = targetRow.getBoundingClientRect();
      const topZone = rect.top + rect.height * 0.25;
      const bottomZone = rect.top + rect.height * 0.75;
      const draggingFolder = dragEl.dataset.nodeType === 'folder';
      const wouldCycle = draggingFolder && _isDescendant(dragEl.dataset.nodeId, allFolders, targetRow.dataset.nodeId);

      if (targetRow.dataset.nodeType === 'folder' && e.clientY > topZone && e.clientY < bottomZone && !wouldCycle) {
        targetRow.classList.add('drop-target-folder');
        hoverFolderRow = targetRow;
        return;
      }

      const targetList = targetRow.parentElement;
      if (targetList !== dragEl.parentElement) return; // plain reorder only within the same level
      if (e.clientY < rect.top + rect.height / 2) {
        targetList.insertBefore(dragEl, targetRow);
      } else {
        targetList.insertBefore(dragEl, targetRow.nextSibling);
      }
    });

    treeRoot.addEventListener('dragend', async () => {
      if (!dragEl) return;
      dragEl.classList.remove('dragging');
      const draggedType = dragEl.dataset.nodeType;
      const draggedId = dragEl.dataset.nodeId;
      const sourceList = dragEl.parentElement;

      if (hoverFolderRow) {
        const targetFolderId = hoverFolderRow.dataset.nodeId;
        hoverFolderRow.classList.remove('drop-target-folder');
        hoverFolderRow = null;
        dragEl = null;
        await _reparentNode(col, allFolders, allRequests, rerender, draggedType, draggedId, targetFolderId);
        return;
      }

      dragEl = null;
      const parentFolderId = sourceList.dataset.parentFolderId || null;
      const items = [...sourceList.querySelectorAll(':scope > [data-node-type]')].map(el => ({
        type: el.dataset.nodeType, id: el.dataset.nodeId,
      }));
      const res = await window.api('PUT', `/collections/${col.id}/tree-order`, { parent_folder_id: parentFolderId, items });
      if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
      items.forEach((it, idx) => {
        const arr = it.type === 'folder' ? allFolders : allRequests;
        const n = arr.find(x => x.id === it.id);
        if (n) n.order_index = idx;
      });
    });
  }

  async function _reparentNode(col, allFolders, allRequests, rerender, draggedType, draggedId, newParentFolderId) {
    const patchUrl = draggedType === 'folder' ? `/api-folders/${draggedId}` : `/api-requests/${draggedId}`;
    const patchBody = draggedType === 'folder' ? { parent_folder_id: newParentFolderId } : { folder_id: newParentFolderId };
    const res = await window.api('PATCH', patchUrl, patchBody);
    if (res.ok === false) { await window._alertDialog('Move failed: ' + res.error); return; }

    const movedList = draggedType === 'folder' ? allFolders : allRequests;
    const moved = movedList.find(n => n.id === draggedId);
    if (moved) {
      if (draggedType === 'folder') moved.parent_folder_id = newParentFolderId;
      else moved.folder_id = newParentFolderId;
    }

    const siblingFolders = allFolders.filter(f => f.parent_folder_id === newParentFolderId && f.id !== draggedId);
    const siblingRequests = allRequests.filter(r => r.folder_id === newParentFolderId && r.id !== draggedId);
    const destItems = [
      ...siblingFolders.map(f => ({ type: 'folder', id: f.id })),
      ...siblingRequests.map(r => ({ type: 'request', id: r.id })),
      { type: draggedType, id: draggedId },
    ];
    const orderRes = await window.api('PUT', `/collections/${col.id}/tree-order`, {
      parent_folder_id: newParentFolderId, items: destItems,
    });
    if (orderRes.ok === false) { await window._alertDialog('Error: ' + orderRes.error); return; }
    destItems.forEach((it, idx) => {
      const arr = it.type === 'folder' ? allFolders : allRequests;
      const n = arr.find(x => x.id === it.id);
      if (n) n.order_index = idx;
    });

    rerender();
  }

  // ---- Drag-and-drop: collections themselves ----

  function _wireCollectionOrderDrag() {
    let dragEl = null;

    container.addEventListener('dragstart', e => {
      const header = e.target.closest('.api-collection-header');
      if (!header) return;
      dragEl = header.closest('.api-collection-section');
      dragEl.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    container.addEventListener('dragover', e => {
      if (!dragEl) return;
      const targetHeader = e.target.closest('.api-collection-header');
      const target = targetHeader ? targetHeader.closest('.api-collection-section') : null;
      if (!target || target === dragEl || target.parentElement !== container) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = target.getBoundingClientRect();
      if (e.clientY < rect.top + rect.height / 2) {
        container.insertBefore(dragEl, target);
      } else {
        container.insertBefore(dragEl, target.nextSibling);
      }
    });

    container.addEventListener('dragend', async () => {
      if (!dragEl) return;
      dragEl.classList.remove('dragging');
      dragEl = null;
      const ids = [...container.querySelectorAll('.api-collection-section')].map(s => s.dataset.collectionId);
      const res = await window.api('PUT', '/collections/order', { collection_ids: ids });
      if (res.ok === false) await window._alertDialog('Error: ' + res.error);
    });
  }

  // ---- Collection-level actions (unchanged from before this rewrite) ----

  async function _runCollection(colId, colName, envName) {
    const confirmed = await window._confirmDialog(
      `Run '${colName}'?`,
      'All requests in this collection will be executed in order.',
      'Run'
    );
    if (!confirmed) return;
    const res = await window.api('POST', `/collections/${colId}/run`, { env_name: envName || null });
    if (res.ok === false) {
      await window._alertDialog('Run failed: ' + res.error);
      return;
    }
    if (onRunStarted && res.run_id) {
      onRunStarted(res.run_id, colId, colName);
    }
  }

  async function _exportCollection(colId, colName, fmt) {
    const res = await fetch(`/api/collections/${encodeURIComponent(colId)}/export?format=${fmt}`, { method: 'POST' });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).error || msg; } catch (_) {}
      await window._alertDialog('Export failed: ' + msg);
      return;
    }
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/);
    const filename = match ? match[1] : `${colName}.${fmt === 'postman' ? 'postman_collection.json' : 'zip'}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function _deleteCollection(colId, colName) {
    const confirmed = await window._confirmDialog(`Delete '${colName}'?`, 'All requests in this collection will be permanently deleted.', 'Delete', 'btn btn-sm btn-danger');
    if (!confirmed) return;
    const res = await window.api('DELETE', `/collections/${colId}`);
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  async function _createCollection() {
    const name = await window._promptDialog('Collection name:');
    if (!name) return;
    const res = await window.api('POST', '/collections', { name: name.trim() });
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function setActiveRequestId(requestId) {
    _activeRequestId = requestId || null;
  }

  reload();
  return { reload, setActiveRequestId, updateRunningRuns };
}
