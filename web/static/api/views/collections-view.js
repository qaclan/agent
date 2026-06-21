/**
 * renderCollectionsView(container, onSelectRequest)
 * container: DOM element to render into
 * onSelectRequest: (requestId) => void
 */
export function renderCollectionsView(container, onSelectRequest) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading...</div>';

  async function reload() {
    const res = await window.api('GET', '/collections');
    const collections = res.collections || [];
    container.innerHTML = '';

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
      leftSide.innerHTML = `<strong>${_esc(col.name)}</strong> <span class="text-muted text-sm">(${col.request_count})</span>`;
      header.appendChild(leftSide);

      const rightSide = document.createElement('span');
      rightSide.style.display = 'flex';
      rightSide.style.gap = '4px';

      const runBtn = document.createElement('button');
      runBtn.className = 'btn btn-xs btn-ghost';
      runBtn.textContent = '▶ Run';
      runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name); };
      rightSide.appendChild(runBtn);

      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-xs btn-ghost';
      delBtn.style.color = 'var(--danger, #e53e3e)';
      delBtn.textContent = '✕';
      delBtn.title = 'Delete collection';
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
        if (e.target === runBtn || e.target === expandBtn) return;
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
          const methodClass = `method-${req.method}`;
          item.innerHTML = `<span class="method-badge ${methodClass}">${_esc(req.method)}</span> <span>${_esc(req.name)}</span>`;
          item.onclick = () => {
            container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            onSelectRequest(req.id);
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
          onSelectRequest(null, col.id);
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
  }

  async function _runCollection(colId, colName) {
    const confirmed = await window._confirmDialog(`Run '${colName}'?`, 'All requests in this collection will be executed in order.', 'Run');
    if (!confirmed) return;
    const res = await window.api('POST', `/collections/${colId}/run`, {});
    if (res.ok === false) {
      await window._alertDialog('Run failed: ' + res.error);
    } else {
      window._toast(`Run complete: ${res.passed}/${res.total} passed`);
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
}
