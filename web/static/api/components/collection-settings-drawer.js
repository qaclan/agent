import { renderCollectionSettingsTabs } from '../views/collection-detail-view.js';

/**
 * openCollectionSettingsDrawer(col)
 *
 * A slide-over panel, headed "Collection: <name>", that hosts the collection's
 * Auth / Variables / Schema Check / Negative settings — the same tab renderers
 * the collection-detail page uses (renderCollectionSettingsTabs), so there is one
 * implementation of each and no drift.
 *
 * It is opened from the request-editor header. The editor's own request-scoped
 * tab strip is left untouched, so a setting that exists at both scopes never
 * shows as two same-named tabs; the drawer's heading names the scope.
 *
 * `col` must be the full collection object (id, name, env_name, auth_type,
 * auth_config, schema_check_default, negative_check_default).
 *
 * opts:
 *   tab      — open on this tab id ('auth' | 'vars' | 'schema' | 'negative').
 *   addRow   — open on Variables and append a new empty row, focused (add-variable).
 *   onClose  — called when the drawer closes (e.g. to refresh the caller's vars).
 */
export function openCollectionSettingsDrawer(col, opts = {}) {
  const _esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  let _tabsCtl = null;

  const backdrop = document.createElement('div');
  backdrop.style.cssText = 'position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.4);opacity:0;transition:opacity .18s;';

  const panel = document.createElement('div');
  panel.style.cssText = [
    'position:fixed;top:0;right:0;bottom:0;z-index:1001;',
    'width:min(560px,92vw);background:var(--bg-panel,var(--bg-elevated));',
    'border-left:1px solid var(--border-default);',
    'box-shadow:-8px 0 32px rgba(0,0,0,.35);',
    'display:flex;flex-direction:column;',
    'transform:translateX(100%);transition:transform .2s ease;',
  ].join('');

  const head = document.createElement('div');
  head.style.cssText = 'display:flex;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid var(--border-default);flex-shrink:0;';
  head.innerHTML = `
    <div style="flex:1;min-width:0;">
      <div style="font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);">Collection settings</div>
      <div style="font-size:15px;font-weight:700;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(col.name)}</div>
    </div>`;
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'btn btn-sm btn-ghost';
  closeBtn.style.cssText = 'flex-shrink:0;font-size:16px;line-height:1;padding:4px 10px;';
  closeBtn.textContent = '×';
  closeBtn.title = 'Close';
  head.appendChild(closeBtn);
  panel.appendChild(head);

  const body = document.createElement('div');
  body.style.cssText = 'flex:1;overflow-y:auto;padding:20px;';
  const host = document.createElement('div');
  body.appendChild(host);
  panel.appendChild(body);

  let _closed = false;
  function _close() {
    if (_closed) return;
    _closed = true;
    document.removeEventListener('keydown', _onKey);
    if (_tabsCtl) { try { _tabsCtl.destroy(); } catch (_) {} _tabsCtl = null; }
    backdrop.style.opacity = '0';
    panel.style.transform = 'translateX(100%)';
    setTimeout(() => {
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      if (panel.parentNode) panel.parentNode.removeChild(panel);
    }, 200);
    try { opts.onClose && opts.onClose(); } catch (_) {}
  }

  function _onKey(e) { if (e.key === 'Escape') _close(); }

  closeBtn.onclick = _close;
  backdrop.onclick = _close;
  document.addEventListener('keydown', _onKey);

  document.body.appendChild(backdrop);
  document.body.appendChild(panel);

  // Mount the shared settings tabs (Auth / Variables / Schema Check / Negative).
  _tabsCtl = renderCollectionSettingsTabs(host, col);

  // Trigger the slide-in transition after the elements are in the DOM, then run
  // any requested tab/add-row action so focus lands after the first paint.
  requestAnimationFrame(() => {
    backdrop.style.opacity = '1';
    panel.style.transform = 'translateX(0)';
    if (opts.addRow) _tabsCtl.addVariable();
    else if (opts.tab) _tabsCtl.openTab(opts.tab);
  });
}
