import { emitEnvChanged } from './env-events.js';

/**
 * createEnvSelector({ collectionId, envName, onChange }) → { el, open, setEnv, highlight, destroy, get value }
 *
 * A reusable environment picker rendered as a CUSTOM dropdown (trigger button +
 * fixed-positioned menu), not a native <select> — so it can be opened
 * programmatically (`open()`, used by the variable-picker empty state) and
 * behaves identically across browsers.
 *
 * Menu items: "No environment", each project environment (GET /api/envs), and
 * "+ New environment…". Selecting binds to the collection via
 * PATCH /api/collections/<id> (the single source of truth, api_collections.env_name),
 * toasts a confirmation, and emits the shared env-changed signal so every other
 * view for that collection converges. Creating binds the new env in one step.
 *
 * Mount `.el` anywhere. `setEnv(name)` updates the shown value WITHOUT re-binding
 * (use it from an env-changed subscription). `destroy()` removes the body-level
 * menu and global listeners — call it when the mounting view is torn down.
 */
export function createEnvSelector(opts = {}) {
  let { collectionId = null, envName = null, onChange = () => {} } = opts;
  let _names = [];
  let _open = false;

  const wrap = document.createElement('span');
  wrap.style.cssText = 'display:inline-flex;';

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.title = 'Environment for this collection';
  trigger.style.cssText = [
    'display:inline-flex;align-items:center;gap:6px;max-width:180px;',
    'font-size:12px;padding:4px 8px;border:1px solid var(--border-default);',
    'border-radius:6px;background:var(--bg-panel);color:var(--text-primary);cursor:pointer;',
  ].join('');
  const label = document.createElement('span');
  label.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  const caret = document.createElement('span');
  caret.textContent = '▾';
  caret.style.cssText = 'flex-shrink:0;opacity:.7;font-size:10px;';
  trigger.appendChild(label);
  trigger.appendChild(caret);
  wrap.appendChild(trigger);

  const menu = document.createElement('div');
  menu.style.cssText = [
    'position:fixed;z-index:1300;min-width:180px;max-height:280px;overflow-y:auto;',
    'background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:7px;',
    'box-shadow:0 4px 18px rgba(0,0,0,.28);padding:4px;display:none;',
  ].join('');
  document.body.appendChild(menu);

  function _renderLabel() { label.textContent = envName || 'No environment'; }

  function _mkItem(text, o = {}) {
    const it = document.createElement('div');
    it.style.cssText = 'padding:6px 10px;font-size:12px;border-radius:5px;cursor:pointer;white-space:nowrap;color:' + (o.accent ? 'var(--accent)' : 'var(--text-primary)') + ';';
    if (o.selected) it.style.background = 'var(--bg-panel)';
    it.textContent = text;
    it.onmouseenter = () => { it.style.background = 'var(--bg-panel)'; };
    it.onmouseleave = () => { it.style.background = o.selected ? 'var(--bg-panel)' : ''; };
    it.onclick = () => { _closeMenu(); o.onClick && o.onClick(); };
    return it;
  }

  function _renderMenu() {
    menu.innerHTML = '';
    menu.appendChild(_mkItem('No environment', { selected: !envName, onClick: () => _bind('') }));
    _names.forEach(name => menu.appendChild(_mkItem(name, { selected: name === envName, onClick: () => _bind(name) })));
    const div = document.createElement('div');
    div.style.cssText = 'height:1px;background:var(--border-default);margin:4px 2px;';
    menu.appendChild(div);
    menu.appendChild(_mkItem('+ New environment…', { accent: true, onClick: () => _createNew() }));
  }

  function _position() {
    const r = trigger.getBoundingClientRect();
    menu.style.minWidth = Math.max(r.width, 180) + 'px';
    menu.style.left = Math.min(r.left, window.innerWidth - 200) + 'px';
    const below = window.innerHeight - r.bottom;
    menu.style.top = (below >= 160 ? r.bottom + 4 : Math.max(8, r.top - 4 - Math.min(280, menu.scrollHeight))) + 'px';
  }

  function _openMenu() {
    _renderMenu();
    menu.style.display = 'block';
    _position();
    _open = true;
  }
  function _closeMenu() { menu.style.display = 'none'; _open = false; }

  trigger.onclick = (e) => { e.stopPropagation(); _open ? _closeMenu() : _openMenu(); };

  const _onDocDown = (e) => { if (_open && !menu.contains(e.target) && !trigger.contains(e.target)) _closeMenu(); };
  const _onKey = (e) => { if (_open && e.key === 'Escape') _closeMenu(); };
  document.addEventListener('mousedown', _onDocDown);
  document.addEventListener('keydown', _onKey);

  async function _loadEnvs() {
    try {
      const res = await window.api('GET', '/envs');
      _names = (res.environments || res.envs || [])
        .map(e => (typeof e === 'string' ? e : e.name || ''))
        .filter(Boolean);
    } catch (_) {
      _names = [];
    }
    if (_open) _renderMenu();
  }

  // Persist the binding, then broadcast. Reverts the shown value on failure.
  async function _bind(name) {
    const next = name || null;
    if (next === envName) return true;
    const prev = envName;
    envName = next;
    _renderLabel();
    if (collectionId != null) {
      const res = await window.api('PATCH', `/collections/${collectionId}`, { env_name: envName });
      if (res && res.ok === false) {
        envName = prev;
        _renderLabel();
        await window._alertDialog?.('Could not set environment: ' + (res.error || 'unknown error'));
        return false;
      }
    }
    window._toast?.(envName ? `Environment → ${envName}` : 'Environment cleared');
    onChange(envName);
    emitEnvChanged(collectionId, envName);
    return true;
  }

  async function _createNew() {
    const raw = await (window._promptDialog
      ? window._promptDialog('New environment name', '')
      : Promise.resolve(window.prompt('New environment name')));
    const name = (raw || '').trim();
    if (!name) return;
    const res = await window.api('POST', '/envs', { name });
    if (res && res.ok === false) {
      await window._alertDialog?.('Could not create environment: ' + (res.error || 'name may already exist'));
      return;
    }
    await _loadEnvs();
    await _bind(name);
  }

  _renderLabel();
  _loadEnvs();

  return {
    el: wrap,
    open() {
      // Defer to a macrotask so the click that invoked us (e.g. an empty-state
      // button) fully settles first — otherwise that same mousedown reaches the
      // outside-close handler and shuts the menu the instant it opens.
      setTimeout(() => {
        _openMenu();
        // Refresh the list in case environments changed since mount.
        _loadEnvs().then(() => { if (_open) { _renderMenu(); _position(); } });
      }, 0);
    },
    setEnv(name) {
      envName = name || null;
      _renderLabel();
      if (_open) _renderMenu();
    },
    highlight() {
      trigger.focus();
      const prev = trigger.style.boxShadow;
      trigger.style.boxShadow = '0 0 0 2px var(--accent)';
      setTimeout(() => { trigger.style.boxShadow = prev; }, 1200);
    },
    destroy() {
      _closeMenu();
      document.removeEventListener('mousedown', _onDocDown);
      document.removeEventListener('keydown', _onKey);
      if (menu.parentNode) menu.parentNode.removeChild(menu);
    },
    get value() { return envName; },
  };
}
