/**
 * createVarPicker(opts) → { open(anchorEl, onSelect, initialQuery?), close() }
 * opts.getVars: async () => [{key, value, is_secret?, group?}]
 * group: 'Environment' | 'Collection' | undefined — renders section headers when present
 */
export function createVarPicker(opts = {}) {
  const { getVars = async () => [] } = opts;

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:1000;pointer-events:none;';
  overlay.style.display = 'none';
  document.body.appendChild(overlay);

  const pop = document.createElement('div');
  pop.style.cssText = [
    'position:fixed;z-index:1001;pointer-events:all;',
    'background:var(--surface-1,#fff);',
    'border:1px solid var(--border);border-radius:7px;',
    'box-shadow:0 4px 18px rgba(0,0,0,.18);',
    'width:300px;overflow:hidden;',
    'display:flex;flex-direction:column;',
  ].join('');
  document.body.appendChild(pop);
  pop.style.display = 'none';

  document.addEventListener('mousedown', (e) => {
    if (overlay.style.display !== 'none' && !pop.contains(e.target)) _close();
  });

  const searchWrap = document.createElement('div');
  searchWrap.style.cssText = 'padding:7px 10px;border-bottom:1px solid var(--border);';
  const searchInp = document.createElement('input');
  searchInp.type = 'text';
  searchInp.placeholder = 'Filter variables…';
  searchInp.style.cssText = 'width:100%;font-size:12px;border:none;outline:none;background:transparent;color:var(--text);';
  searchWrap.appendChild(searchInp);
  pop.appendChild(searchWrap);

  const list = document.createElement('div');
  list.style.cssText = 'max-height:240px;overflow-y:auto;';
  pop.appendChild(list);

  let _allVars = [];
  let _onSelect = null;
  let _cacheTs = 0;
  let _activeIdx = -1;
  let _itemEls = [];

  function _renderList(filter) {
    list.innerHTML = '';
    _activeIdx = -1;
    _itemEls = [];

    const q = (filter || '').trim().toLowerCase();
    const filtered = q ? _allVars.filter(v => v.key.toLowerCase().includes(q)) : _allVars;

    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding:10px 12px;font-size:12px;color:var(--text-muted);';
      empty.textContent = _allVars.length
        ? 'No matching variables.'
        : 'No variables available. Select an environment or add collection variables.';
      list.appendChild(empty);
      return;
    }

    const hasGroups = filtered.some(v => v.group);

    if (!hasGroups) {
      filtered.forEach(v => _addItemRow(v));
      return;
    }

    const groups = {};
    const groupOrder = [];
    filtered.forEach(v => {
      const g = v.group || 'Other';
      if (!groups[g]) { groups[g] = []; groupOrder.push(g); }
      groups[g].push(v);
    });

    groupOrder.forEach((g, gi) => {
      const hdr = document.createElement('div');
      hdr.style.cssText = [
        'padding:4px 12px 2px;font-size:10px;font-weight:600;',
        'text-transform:uppercase;letter-spacing:.07em;',
        'color:var(--text-muted);',
        gi > 0 ? 'border-top:1px solid var(--border);margin-top:2px;padding-top:6px;' : '',
      ].join('');
      hdr.textContent = g;
      list.appendChild(hdr);
      groups[g].forEach(v => _addItemRow(v));
    });
  }

  function _addItemRow(v) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;font-size:12px;';
    row.onmouseenter = () => {
      _clearHighlight();
      row.style.background = 'var(--surface-2)';
      _activeIdx = _itemEls.indexOf(row);
    };
    row.onmouseleave = () => {
      if (_itemEls[_activeIdx] !== row) row.style.background = '';
    };
    row.onclick = () => _pick(v.key);

    const keyEl = document.createElement('span');
    keyEl.style.cssText = 'font-family:var(--font-mono);font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    keyEl.textContent = v.key;

    const valEl = document.createElement('span');
    valEl.style.cssText = 'color:var(--text-muted);max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0;font-size:11px;';
    const displayVal = v.is_secret ? '••••••••' : String(v.value || '');
    valEl.textContent = displayVal || '(empty)';
    if (!displayVal) valEl.style.fontStyle = 'italic';

    row.appendChild(keyEl);
    row.appendChild(valEl);
    list.appendChild(row);
    _itemEls.push(row);
  }

  function _clearHighlight() {
    _itemEls.forEach(r => r.style.background = '');
  }

  function _pick(key) {
    if (_onSelect) _onSelect(`{{${key}}}`);
    _close();
  }

  function _close() {
    overlay.style.display = 'none';
    pop.style.display = 'none';
    searchInp.value = '';
  }

  searchInp.oninput = () => _renderList(searchInp.value);

  searchInp.onkeydown = (e) => {
    if (!_itemEls.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _activeIdx = Math.min(_activeIdx + 1, _itemEls.length - 1);
      _clearHighlight();
      _itemEls[_activeIdx].style.background = 'var(--surface-2)';
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _activeIdx = Math.max(_activeIdx - 1, 0);
      _clearHighlight();
      _itemEls[_activeIdx].style.background = 'var(--surface-2)';
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (_itemEls[_activeIdx]) _itemEls[_activeIdx].click();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      _close();
    }
  };

  function open(anchorEl, onSelect, initialQuery = '') {
    _onSelect = onSelect;
    const isAlreadyOpen = overlay.style.display !== 'none';

    overlay.style.display = '';
    pop.style.display = 'flex';

    if (!isAlreadyOpen) {
      const rect = anchorEl.getBoundingClientRect();
      const popH = 300;
      const below = window.innerHeight - rect.bottom;
      const top = below >= popH || rect.top < popH
        ? rect.bottom + 4
        : rect.top - popH - 4;
      const left = Math.min(rect.left, window.innerWidth - 310);
      pop.style.top = top + 'px';
      pop.style.left = left + 'px';
    }

    searchInp.value = initialQuery;
    _renderList(initialQuery);

    const now = Date.now();
    if (!_allVars.length || now - _cacheTs > 30000) {
      getVars().then(vars => {
        _allVars = vars || [];
        _cacheTs = Date.now();
        _renderList(searchInp.value);
        if (!isAlreadyOpen) searchInp.focus();
      }).catch(() => { _allVars = []; _renderList(''); });
    } else {
      if (!isAlreadyOpen) searchInp.focus();
    }
  }

  return { open, close: _close };
}
