/**
 * renderCollectionDetailView(container, col, runId, onViewRun, onBack)
 * Shows collection info and, if runId provided, a live summary card with Stop button.
 * Polls GET /api/api-collection-runs/<runId> every 2s while RUNNING.
 * Sets container.__destroyRunView for teardown by parent.
 */
export function renderCollectionDetailView(container, col, runId, onViewRun, onBack) {
  let _pollTimer = null;
  let _destroyed = false;

  function _destroy() {
    _destroyed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }
  container.__destroyRunView = _destroy;

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _renderCard(run) {
    const el = document.getElementById('cdv-card');
    if (!el) return;
    if (!run) { el.style.display = 'none'; return; }

    const isRunning   = run.status === 'RUNNING';
    const done        = (run.request_results || []).length;
    const total       = run.total || 0;
    const pct         = total > 0 ? Math.round(done / total * 100) : 0;
    const statusColor = isRunning      ? 'var(--warning,#f59e0b)'
      : run.status === 'PASSED'        ? 'var(--success,#22c55e)'
      :                                  'var(--danger,#ef4444)';

    el.style.display = '';
    el.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
        <span style="font-size:12px;font-weight:600;color:${statusColor}">
          ${isRunning ? '<span style="animation:cdv-pulse 1s infinite;display:inline-block;margin-right:4px">⟳</span>' : ''}
          ${_esc(run.status)}  ·  ${done}/${total}  ·  ${run.passed} passed · ${run.failed} failed
        </span>
        <div style="display:flex;gap:6px;">
          ${isRunning ? `<button class="btn btn-xs btn-danger" id="cdv-stop">■ Stop</button>` : ''}
          <button class="btn btn-xs btn-primary" id="cdv-view">View Progress →</button>
        </div>
      </div>
      <div style="height:3px;background:var(--border-subtle,rgba(255,255,255,.1));border-radius:2px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:${statusColor};border-radius:2px;transition:width .4s;"></div>
      </div>`;

    const viewBtn = document.getElementById('cdv-view');
    if (viewBtn) viewBtn.onclick = () => { _destroy(); if (onViewRun) onViewRun(run.id); };

    const stopBtn = document.getElementById('cdv-stop');
    if (stopBtn) stopBtn.onclick = async () => {
      stopBtn.disabled = true; stopBtn.textContent = 'Stopping…';
      await window.api('POST', `/api-collection-runs/${run.id}/stop`);
    };

    if (!isRunning) {
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    }
  }

  async function _poll() {
    if (_destroyed || !runId) return;
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (res.ok && res.run) _renderCard(res.run);
    } catch (_) {}
  }

  async function _init() {
    container.innerHTML = `
      <style>@keyframes cdv-pulse{0%,100%{opacity:1}50%{opacity:.35}}</style>
      <div style="padding:16px 18px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
          <button class="btn btn-xs btn-ghost" id="cdv-back">← Back</button>
          <span style="font-size:14px;font-weight:700;">${_esc(col.name)}</span>
          <span style="font-size:11px;color:var(--text-muted)">${col.request_count || 0} requests</span>
        </div>
        <div id="cdv-card" style="display:none;background:var(--bg-panel,rgba(255,255,255,.04));
          border:1px solid var(--border-default,rgba(255,255,255,.12));border-radius:8px;
          padding:12px 14px;margin-bottom:16px;"></div>
        <div style="font-size:12px;color:var(--text-muted);">
          Select a request from the left panel to view or edit it.
        </div>
      </div>`;

    document.getElementById('cdv-back').onclick = () => { _destroy(); if (onBack) onBack(); };

    if (runId) {
      await _poll();
      _pollTimer = setInterval(_poll, 2000);
    }
  }

  _init();
}
