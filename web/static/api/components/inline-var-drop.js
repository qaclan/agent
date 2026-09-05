/**
 * createInlineVarDrop(getVars, opts) → { open, close, isOpen, handleKeydown, watchInput }
 *
 * Inline autocomplete dropdown for {{VAR}} token insertion.
 * Does NOT steal focus — the source input keeps focus throughout.
 *
 * watchInput(inp): attach to any <input> or <textarea> to get automatic
 * {{ detection, dropdown display, keyboard nav, and token insertion.
 *
 * opts.emptyActions: array (or function returning an array) of { label, onClick }.
 *   When there are NO variables at all, these render as buttons in the empty
 *   state so the user can act (select/create an environment, add a variable)
 *   without leaving the field. Presentation-only — the caller owns the logic.
 */
export function createInlineVarDrop(getVars, opts = {}) {
  const _emptyActions = opts.emptyActions;
  let _allVars = [];
  let _cacheTs = 0;
  let _activeIdx = -1;
  let _items = [];
  let _onSelect = null;

  const pop = document.createElement('div');
  pop.style.cssText = [
    'position:fixed;z-index:1002;',
    'background:var(--bg-elevated);',
    'border:1px solid var(--border-default);border-radius:7px;',
    'box-shadow:0 4px 18px rgba(0,0,0,.28);',
    'width:280px;max-height:220px;overflow-y:auto;display:none;',
  ].join('');
  document.body.appendChild(pop);

  document.addEventListener('mousedown', (e) => {
    if (pop.style.display !== 'none' && !pop.contains(e.target)) _close();
  }, true);

  function _position(inp) {
    const r = inp.getBoundingClientRect();
    pop.style.left = Math.min(r.left, window.innerWidth - 290) + 'px';
    const below = window.innerHeight - r.bottom;
    pop.style.top = (below >= 120 ? r.bottom + 2 : r.top - 222) + 'px';
  }

  function _clearHL() {
    _items.forEach(i => { i.el.style.background = ''; });
  }

  function _resolveEmptyActions() {
    const a = typeof _emptyActions === 'function' ? _emptyActions() : _emptyActions;
    return Array.isArray(a) ? a.filter(Boolean) : [];
  }

  function _renderEmptyActions(parent, acts) {
    if (!acts.length) return;
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:2px 12px 10px;';
    acts.forEach(a => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = a.label;
      b.style.cssText = 'font-size:11px;padding:3px 8px;border:1px solid var(--border-default);border-radius:5px;background:var(--bg-panel);color:var(--text-primary);cursor:pointer;';
      // mousedown + preventDefault: fire before the source input blurs, then
      // close so the action (which may open a dialog) has a clean stage.
      b.onmousedown = (e) => { e.preventDefault(); _close(); Promise.resolve().then(() => a.onClick && a.onClick()); };
      bar.appendChild(b);
    });
    parent.appendChild(bar);
  }

  function _render(filter) {
    pop.innerHTML = '';
    _activeIdx = -1;
    _items = [];

    const q = (filter || '').trim().toLowerCase();
    const filtered = q ? _allVars.filter(v => v.key.toLowerCase().includes(q)) : _allVars;

    if (!filtered.length) {
      const em = document.createElement('div');
      em.style.cssText = 'padding:8px 12px;font-size:12px;color:var(--text-muted);';
      const acts = _resolveEmptyActions();
      em.textContent = _allVars.length
        ? 'No matching variables'
        : (acts.length ? 'No variables yet' : 'No variables — add env or collection vars');
      pop.appendChild(em);
      if (!_allVars.length) _renderEmptyActions(pop, acts);
      return;
    }

    const hasGroups = filtered.some(v => v.group);
    if (!hasGroups) {
      filtered.forEach(_addItem);
      return;
    }

    const groups = {}, order = [];
    filtered.forEach(v => {
      const g = v.group || 'Other';
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(v);
    });
    order.forEach((g, i) => {
      const hdr = document.createElement('div');
      hdr.style.cssText = `padding:${i > 0 ? '6px' : '4px'} 12px 2px;font-size:10px;font-weight:600;` +
        `text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);` +
        (i > 0 ? 'border-top:1px solid var(--border-default);' : '');
      hdr.textContent = g;
      pop.appendChild(hdr);
      groups[g].forEach(_addItem);
    });
  }

  function _addItem(v) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;font-size:12px;color:var(--text-primary);';
    row.onmouseenter = () => {
      _clearHL();
      row.style.background = 'var(--bg-panel)';
      _activeIdx = _items.findIndex(i => i.el === row);
    };
    row.onmouseleave = () => {
      if (_items[_activeIdx]?.el !== row) row.style.background = '';
    };
    // mousedown (not click) so we fire before blur and can e.preventDefault() to keep focus in inp
    row.onmousedown = (e) => { e.preventDefault(); _pick(v.key); };

    if (v.group === 'Environment' || v.group === 'Collection') {
      const dot = document.createElement('span');
      dot.className = 'var-source-dot ' + (v.group === 'Environment' ? 'var-source-dot--env' : 'var-source-dot--col');
      dot.title = v.group;
      row.appendChild(dot);
    }

    const keyEl = document.createElement('span');
    keyEl.style.cssText = 'font-family:var(--font-mono);font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    keyEl.textContent = v.key;

    const valEl = document.createElement('span');
    valEl.style.cssText = 'color:var(--text-muted);max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0;font-size:11px;';
    const dv = v.is_secret ? '••••••••' : String(v.value || '');
    valEl.textContent = dv || '(empty)';
    if (!dv) valEl.style.fontStyle = 'italic';

    row.appendChild(keyEl);
    row.appendChild(valEl);
    pop.appendChild(row);
    _items.push({ el: row, key: v.key });
  }

  function _pick(key) {
    if (_onSelect) _onSelect(`{{${key}}}`);
    _close();
  }

  function _close() {
    pop.style.display = 'none';
    _onSelect = null;
  }

  function open(inp, onSelect, filter) {
    _onSelect = onSelect;
    pop.style.display = 'block';
    _render(filter);
    _position(inp);

    const now = Date.now();
    if (!_allVars.length || now - _cacheTs > 30000) {
      getVars().then(vars => {
        _allVars = vars || [];
        _cacheTs = Date.now();
        _render(filter);
        _position(inp);
      }).catch(() => { _allVars = []; _render(''); });
    }
  }

  function isOpen() {
    return pop.style.display !== 'none';
  }

  function invalidate() { _cacheTs = 0; }

  function handleKeydown(e) {
    if (!isOpen()) return false;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _activeIdx = Math.min(_activeIdx + 1, _items.length - 1);
      _clearHL();
      if (_items[_activeIdx]) _items[_activeIdx].el.style.background = 'var(--bg-panel)';
      return true;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      _activeIdx = Math.max(_activeIdx - 1, 0);
      _clearHL();
      if (_items[_activeIdx]) _items[_activeIdx].el.style.background = 'var(--bg-panel)';
      return true;
    }
    if (e.key === 'Enter') {
      if (_items[_activeIdx]) {
        e.preventDefault();
        _pick(_items[_activeIdx].key);
        return true;
      }
      return false;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      _close();
      return true;
    }
    return false;
  }

  /**
   * Attach inline {{ autocomplete to any <input> or <textarea>.
   * Does not affect other existing event listeners on the element.
   */
  function watchInput(inp) {
    inp.addEventListener('input', (e) => {
      if (!e.isTrusted) return;
      const val = inp.value;
      const caret = inp.selectionStart ?? val.length;
      const before = val.slice(0, caret);
      const openAt = before.lastIndexOf('{{');
      if (openAt !== -1 && !val.slice(openAt + 2).includes('}}')) {
        const partial = before.slice(openAt + 2);
        open(inp, (varToken) => {
          // Re-read current state at selection time (user may have typed more)
          const cv = inp.value;
          const cc = inp.selectionStart ?? cv.length;
          const cb = cv.slice(0, cc);
          const oa = cb.lastIndexOf('{{');
          const at = oa !== -1 ? oa : cc;
          inp.value = cv.slice(0, at) + varToken + cv.slice(cc);
          inp.setSelectionRange(at + varToken.length, at + varToken.length);
          inp.dispatchEvent(new Event('input'));
          inp.focus();
        }, partial);
      } else {
        _close();
      }
    });
    inp.addEventListener('keydown', handleKeydown);
  }

  return { open, close: _close, isOpen, handleKeydown, watchInput, invalidate };
}
