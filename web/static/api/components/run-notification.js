/**
 * notifyRunCompleted(run, { onView }): shows a sticky in-app banner (does
 * not auto-dismiss) and, if OS notification permission is granted, a native
 * Notification too. Both call onView() on click.
 *
 * maybeRequestPermission(): call once, right after a run is detected as
 * newly-started, to ask for OS notification permission via that user
 * gesture rather than on cold page load. No-ops after the first call, or if
 * permission has already been decided.
 */
let _permissionAsked = false;
let _stackEl = null;

function _esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _ensureStack() {
  if (_stackEl) return _stackEl;
  _stackEl = document.createElement('div');
  _stackEl.id = 'run-notification-stack';
  _stackEl.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:10001;' +
    'display:flex;flex-direction:column;gap:8px;align-items:flex-end;';
  document.body.appendChild(_stackEl);
  return _stackEl;
}

function _summaryText(run) {
  const parts = [`${run.passed || 0} passed`, `${run.failed || 0} failed`];
  if (run.error_count) parts.push(`${run.error_count} errors`);
  return parts.join(', ');
}

function _showBanner(run, summary, onView) {
  const stack = _ensureStack();
  const isPass = run.status === 'PASSED';
  const borderColor = isPass ? 'var(--success-border)' : 'var(--danger-border)';
  const titleColor = isPass ? 'var(--success)' : 'var(--danger)';

  const banner = document.createElement('div');
  banner.style.cssText = `background:var(--bg-elevated);border:1px solid ${borderColor};` +
    'border-radius:8px;padding:10px 14px;min-width:260px;max-width:340px;' +
    'box-shadow:var(--shadow-lg);font-size:12px;';
  banner.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
      <div>
        <div style="font-weight:700;color:${titleColor};margin-bottom:2px;">${_esc(run.collection_name)} finished</div>
        <div style="color:var(--text-secondary);">${_esc(summary)}</div>
      </div>
      <button class="rn-dismiss" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px;line-height:1;padding:0;">&#10005;</button>
    </div>
    <button class="rn-view btn btn-xs btn-primary" style="margin-top:8px;width:100%;">View Results</button>`;

  banner.querySelector('.rn-dismiss').onclick = () => banner.remove();
  banner.querySelector('.rn-view').onclick = () => { banner.remove(); onView(); };
  stack.appendChild(banner);
}

function _fireOsNotification(run, summary, onView) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    const n = new Notification(`${run.collection_name} finished`, { body: summary });
    n.onclick = () => { window.focus(); onView(); n.close(); };
  } catch (_) {}
}

export function notifyRunCompleted(run, { onView }) {
  const summary = _summaryText(run);
  _showBanner(run, summary, onView);
  _fireOsNotification(run, summary, onView);
}

export function maybeRequestPermission() {
  if (_permissionAsked) return;
  if (typeof Notification === 'undefined') return;
  if (Notification.permission !== 'default') return;
  _permissionAsked = true;
  Notification.requestPermission().catch(() => {});
}
