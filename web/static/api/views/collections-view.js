/**
 * renderCollectionsView(container, onSelectRequest)
 * container: DOM element to render into
 * onSelectRequest: (requestId) => void
 */
export function renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading...</div>';

  let _runningByColId = {};
  let _runningPollTimer = null;

  async function _refreshRunningStatus() {
    try {
      const res = await window.api('GET', '/api-collection-runs?status=RUNNING');
      const runs = res.runs || [];
      const fresh = {};
      runs.forEach(r => { if (r.collection_id) fresh[r.collection_id] = r.id; });
      const changed = JSON.stringify(fresh) !== JSON.stringify(_runningByColId);
      _runningByColId = fresh;
      if (changed) _updateRunningDots();
      if (Object.keys(_runningByColId).length === 0 && _runningPollTimer) {
        clearInterval(_runningPollTimer);
        _runningPollTimer = null;
      }
    } catch (_) {}
  }

  function _updateRunningDots() {
    document.querySelectorAll('[data-col-dot]').forEach(dot => {
      const colId = dot.dataset.colDot;
      dot.style.display = _runningByColId[colId] ? '' : 'none';
    });
  }

  async function reload() {
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
      const newColBtn = document.createElement('div');
      newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
      newColBtn.textContent = '+ New Collection';
      newColBtn.onclick = _createCollection;
      container.appendChild(newColBtn);
      return;
    }

    collections.forEach(col => {
      const section = document.createElement('div');
      section.className = 'api-collection-section';

      // Collection header row
      const header = document.createElement('div');
      header.className = 'api-collection-item';

      const leftSide = document.createElement('span');
      leftSide.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1;min-width:0;';
      leftSide.innerHTML = `
        <span data-col-dot="${_esc(col.id)}" style="display:none;width:7px;height:7px;border-radius:50%;
          background:var(--warning,#f59e0b);flex-shrink:0;animation:cdot-pulse 1s infinite"></span>
        <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(col.name)}</strong>
        <span class="text-muted text-sm" style="flex-shrink:0;">(${col.request_count})</span>`;
      leftSide.onclick = (e) => {
        e.stopPropagation();
        if (onSelectCollection) {
          const runId = _runningByColId[col.id] || null;
          onSelectCollection(col, runId);
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

      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-xs btn-ghost';
      delBtn.title = 'Delete collection';
      delBtn.style.color = 'var(--danger,#e53e3e)';
      delBtn.textContent = '🗑';
      delBtn.onclick = (e) => { e.stopPropagation(); _deleteCollection(col.id, col.name); };
      rightSide.appendChild(delBtn);

      const expandBtn = document.createElement('button');
      expandBtn.className = 'btn btn-xs btn-ghost';
      expandBtn.textContent = '▾';
      rightSide.appendChild(expandBtn);
      header.appendChild(rightSide);

      section.appendChild(header);

      // Requests list (togglable)
      const reqList = document.createElement('div');
      reqList.className = 'api-requests-list';
      let expanded = true;

      function _toggleExpand() {
        expanded = !expanded;
        reqList.style.display = expanded ? '' : 'none';
        expandBtn.textContent = expanded ? '▾' : '▸';
      }
      header.onclick = (e) => {
        if (rightSide.contains(e.target)) return;
        if (leftSide.contains(e.target)) return;
        _toggleExpand();
      };
      expandBtn.onclick = (e) => { e.stopPropagation(); _toggleExpand(); };

      // Load requests for this collection
      window.api('GET', `/api-requests?collection_id=${col.id}`).then(r => {
        const reqs = r.requests || [];
        reqs.forEach(req => {
          const item = document.createElement('div');
          item.className = 'api-request-item';
          item.dataset.requestId = req.id;

          const badge = document.createElement('span');
          badge.className = `method-badge method-${req.method}`;
          badge.textContent = req.method;

          const name = document.createElement('span');
          name.textContent = req.name;

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
            const res = await window.api('PATCH', `/api-requests/${req.id}`, { collection_id: null });
            if (res.ok === false) {
              await window._alertDialog('Failed: ' + (res.error || 'unknown error'));
              return;
            }
            item.remove();
          };

          item.appendChild(badge);
          item.appendChild(name);
          item.appendChild(removeBtn);

          item.onclick = () => {
            container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            onSelectRequest(req.id, null, col.id, col.env_name);
          };
          reqList.appendChild(item);
        });

        // "New request in collection" button
        const newReqBtn = document.createElement('div');
        newReqBtn.className = 'api-request-item';
        newReqBtn.innerHTML = `<span style="color:var(--text-muted)">+ New Request</span>`;
        newReqBtn.onclick = () => {
          container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
          newReqBtn.classList.add('active');
          onSelectRequest(null, col.id, col.id, col.env_name);
        };
        reqList.appendChild(newReqBtn);
      });

      section.appendChild(reqList);
      container.appendChild(section);
    });

    // "New collection" at bottom
    const newColBtn = document.createElement('div');
    newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
    newColBtn.textContent = '+ New Collection';
    newColBtn.onclick = _createCollection;
    container.appendChild(newColBtn);

    if (_runningPollTimer) clearInterval(_runningPollTimer);
    await _refreshRunningStatus();
    _runningPollTimer = setInterval(_refreshRunningStatus, 3000);
  }

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

  reload();
  return { reload };
}
