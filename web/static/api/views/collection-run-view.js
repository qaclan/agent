/**
 * renderCollectionRunView(container, runId, collectionId, collectionName, onBack)
 * Full run detail page. Polls GET /api/api-collection-runs/<runId> every 1s while RUNNING.
 * Sets container.__destroyRunView for teardown by parent.
 */
export function renderCollectionRunView(container, runId, collectionId, collectionName, onBack) {
  let _pollTimer = null;
  let _elapsedTimer = null;
  let _startedAt = null;
  let _allRequests = [];
  let _destroyed = false;

  function _destroy() {
    _destroyed = true;
    if (_pollTimer)    { clearInterval(_pollTimer);    _pollTimer = null; }
    if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
  }
  container.__destroyRunView = _destroy;

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _startElapsed() {
    if (_elapsedTimer) return;
    _elapsedTimer = setInterval(() => {
      const el = document.getElementById('crv-elapsed');
      if (!el || !_startedAt) return;
      const s = Math.floor((Date.now() - new Date(_startedAt).getTime()) / 1000);
      el.textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    }, 1000);
  }

  function _statusBadge(status) {
    const map = {
      RUNNING: 'var(--warning,#f59e0b)',
      PASSED:  'var(--success,#22c55e)',
      FAILED:  'var(--danger,#ef4444)',
      STOPPED: 'var(--text-muted,#888)',
      ERROR:   'var(--danger,#ef4444)',
    };
    const color = map[status] || 'var(--text-muted,#888)';
    const pulse = status === 'RUNNING'
      ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warning,#f59e0b);margin-right:5px;animation:crv-pulse 1s infinite"></span>'
      : '';
    return `<span style="font-weight:600;font-size:13px;color:${color}">${pulse}${_esc(status)}</span>`;
  }

  function _renderShell() {
    container.innerHTML = `
      <style>
        @keyframes crv-pulse{0%,100%{opacity:1}50%{opacity:.35}}
        @keyframes crv-spin{to{transform:rotate(360deg)}}
        .crv-row{display:flex;align-items:center;gap:8px;padding:9px 16px;border-bottom:1px solid var(--border-subtle,rgba(255,255,255,.07));font-size:12px;cursor:pointer;}
        .crv-row:hover{background:var(--bg-hover,rgba(255,255,255,.04));}
        .crv-detail{padding:12px 18px;background:var(--bg-inset,rgba(0,0,0,.2));border-bottom:1px solid var(--border-subtle,rgba(255,255,255,.07));font-size:11px;display:none;}
        .crv-detail.open{display:block;}
        .crv-spin{display:inline-block;width:11px;height:11px;border:2px solid var(--border,#444);border-top-color:var(--text-muted,#999);border-radius:50%;animation:crv-spin .7s linear infinite;}
        .crv-bar{height:4px;background:var(--border-subtle,rgba(255,255,255,.1));border-radius:2px;overflow:hidden;margin:10px 0 2px;}
        .crv-fill{height:100%;background:var(--primary,#6366f1);border-radius:2px;transition:width .4s;}
        .crv-stat-grid{display:flex;align-items:stretch;border:1px solid var(--border,rgba(255,255,255,.15));border-radius:8px;overflow:hidden;margin-top:10px;}
        .crv-stat-cell{padding:10px 0;display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;min-width:0;}
        .crv-stat-val{font-size:17px;font-weight:700;line-height:1.2;color:var(--text-primary,#eee);}
        .crv-stat-lbl{font-size:9px;color:var(--text-muted,#888);text-transform:uppercase;letter-spacing:.06em;margin-top:3px;}
        .crv-stat-sep{width:1px;background:var(--border,rgba(255,255,255,.15));flex-shrink:0;}
        .crv-method{font-family:monospace;font-size:11px;font-weight:700;min-width:52px;}
        .crv-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        .crv-chevron{font-size:10px;color:var(--text-secondary,#666);min-width:14px;text-align:right;}
        .crv-pass{color:var(--success,#22c55e);font-weight:600;}
        .crv-fail{color:var(--danger,#ef4444);font-weight:600;}
        .crv-err{color:var(--warning,#f59e0b);font-weight:600;}
        .crv-pend{color:var(--text-muted,#888);opacity:.5;}
        pre.crv-body{margin:6px 0 0;padding:8px;background:var(--bg-code,rgba(0,0,0,.25));border-radius:4px;font-size:10px;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;}
      </style>
      <div style="padding:14px 18px;border-bottom:1px solid var(--border,rgba(255,255,255,.1));flex-shrink:0;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <button class="btn btn-xs btn-ghost" id="crv-back">← Back</button>
            <span style="font-size:13px;font-weight:600;">${_esc(collectionName)}</span>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <button class="btn btn-xs btn-danger" id="crv-stop" style="display:none">■ Stop</button>
            <button class="btn btn-xs btn-ghost" id="crv-report" style="display:none">⬇ Report</button>
          </div>
        </div>
        <div class="crv-stat-grid">
          <div class="crv-stat-cell" style="min-width:90px;"><span id="crv-badge"></span></div>
          <div class="crv-stat-sep"></div>
          <div class="crv-stat-cell"><span class="crv-stat-val" id="crv-prog">—</span><span class="crv-stat-lbl">Progress</span></div>
          <div class="crv-stat-sep"></div>
          <div class="crv-stat-cell"><span class="crv-stat-val crv-pass" id="crv-passed-c">0</span><span class="crv-stat-lbl">Passed</span></div>
          <div class="crv-stat-sep"></div>
          <div class="crv-stat-cell"><span class="crv-stat-val crv-fail" id="crv-failed-c">0</span><span class="crv-stat-lbl">Failed</span></div>
          <div class="crv-stat-sep"></div>
          <div class="crv-stat-cell"><span class="crv-stat-val crv-err" id="crv-errors-c">0</span><span class="crv-stat-lbl">Errors</span></div>
          <div class="crv-stat-sep"></div>
          <div class="crv-stat-cell"><span class="crv-stat-val" id="crv-elapsed">00:00</span><span class="crv-stat-lbl">Elapsed</span></div>
        </div>
        <div class="crv-bar"><div class="crv-fill" id="crv-fill" style="width:0%"></div></div>
      </div>
      <div style="overflow-y:auto;flex:1;" id="crv-rows"></div>`;

    document.getElementById('crv-back').onclick = () => { _destroy(); if (onBack) onBack(); };

    document.getElementById('crv-stop').onclick = async () => {
      const btn = document.getElementById('crv-stop');
      if (btn) { btn.disabled = true; btn.textContent = 'Stopping…'; }
      await window.api('POST', `/api-collection-runs/${runId}/stop`);
    };

    document.getElementById('crv-report').onclick = () => {
      window.open(`/api/api-collection-runs/${runId}/report?view=1`, '_blank');
    };
  }

  function _updateHeader(run) {
    const badge   = document.getElementById('crv-badge');
    const fill    = document.getElementById('crv-fill');
    const stopBtn = document.getElementById('crv-stop');
    const repBtn  = document.getElementById('crv-report');
    if (!badge) return;

    badge.innerHTML = _statusBadge(run.status);
    const done  = (run.request_results || []).length;
    const total = run.total || 0;
    const prog    = document.getElementById('crv-prog');
    const passedC = document.getElementById('crv-passed-c');
    const failedC = document.getElementById('crv-failed-c');
    const errorsC = document.getElementById('crv-errors-c');
    if (prog)    prog.textContent    = `${done}/${total}`;
    if (passedC) passedC.textContent = run.passed;
    if (failedC) failedC.textContent = run.failed;
    if (errorsC) errorsC.textContent = run.error_count;
    fill.style.width = total > 0 ? `${Math.round(done / total * 100)}%` : '0%';

    if (stopBtn) stopBtn.style.display = run.status === 'RUNNING' ? '' : 'none';
    if (repBtn)  repBtn.style.display  = run.status !== 'RUNNING' ? '' : 'none';
  }

  function _codeHtml(code) {
    if (code == null) return '<span style="min-width:48px;display:inline-block;"></span>';
    const n = parseInt(code, 10);
    const color = n >= 200 && n < 300 ? 'var(--success,#22c55e)'
      : n >= 300 && n < 400           ? 'var(--info,#60a5fa)'
      : n >= 400                      ? 'var(--danger,#ef4444)'
      :                                 'var(--text-secondary,#555)';
    return `<span style="font-family:monospace;font-size:12px;font-weight:700;color:${color};min-width:48px;text-align:right;display:inline-block;">${code}</span>`;
  }

  function _durHtml(ms) {
    if (ms == null) return '<span style="min-width:64px;display:inline-block;"></span>';
    const color = ms < 300  ? 'var(--success,#22c55e)'
      : ms < 1000           ? 'var(--warning,#f59e0b)'
      :                       'var(--danger,#ef4444)';
    return `<span style="font-size:12px;font-weight:600;color:${color};min-width:64px;text-align:right;display:inline-block;">${ms}ms</span>`;
  }

  function _renderRows(run) {
    const rowsEl = document.getElementById('crv-rows');
    if (!rowsEl) return;

    const byIdx = {};
    (run.request_results || []).forEach(r => { byIdx[r.order_index] = r; });
    const curIdx = run.current_request_index ?? -1;
    const total  = run.total || _allRequests.length;

    let html = '';
    for (let i = 0; i < total; i++) {
      const spine  = _allRequests[i] || {};
      const result = byIdx[i];
      const name   = result ? result.request_name : (spine.name   || `Request ${i + 1}`);
      const method = result ? result.method       : (spine.method || '');

      let badge, codeHtml = '', durHtml = '', chevron = '';
      if (result) {
        if      (result.status === 'PASSED') badge = '<span class="crv-pass">✓</span>';
        else if (result.status === 'FAILED') badge = '<span class="crv-fail">✗</span>';
        else                                 badge = '<span class="crv-err">!</span>';
        codeHtml = _codeHtml(result.status_code);
        durHtml  = _durHtml(result.duration_ms);
        chevron  = '<span class="crv-chevron">▼</span>';
      } else if (i === curIdx) {
        badge    = '<span class="crv-spin"></span>';
        codeHtml = _codeHtml(null);
        durHtml  = _durHtml(null);
      } else {
        badge    = '<span class="crv-pend">·</span>';
        codeHtml = _codeHtml(null);
        durHtml  = _durHtml(null);
      }

      html += `<div class="crv-row" data-i="${i}">
        ${badge}
        <span class="crv-method">${_esc(method)}</span>
        <span class="crv-name">${_esc(name)}</span>
        ${codeHtml}
        ${durHtml}
        ${chevron}
      </div>`;

      if (result) {
        const asserts    = Array.isArray(result.assertion_results) ? result.assertion_results : [];
        const assertHtml = asserts.length
          ? asserts.map(a => `<div style="color:${a.passed ? 'var(--success,#22c55e)' : 'var(--danger,#ef4444)'}">
              ${a.passed ? '✓' : '✗'} ${_esc(a.type)}${a.path ? ' ' + _esc(a.path) : ''}
              ${a.op ? ' ' + _esc(a.op) : ''}${a.value != null ? ' ' + _esc(String(a.value)) : ''}
              ${!a.passed && a.actual != null ? ' → actual: ' + _esc(String(a.actual)) : ''}
            </div>`).join('')
          : '<div style="color:var(--text-muted)">No assertions</div>';
        const rawBody = result.response_body || '';
        let prettyBody = rawBody;
        if (rawBody) {
          try { prettyBody = JSON.stringify(JSON.parse(rawBody), null, 2); } catch (_) {}
        }
        const preview = prettyBody.length > 2000 ? prettyBody.slice(0, 2000) + '\n… (truncated)' : prettyBody;
        const errHtml = result.error_message
          ? `<div style="color:var(--danger,#ef4444);margin-bottom:6px">Error: ${_esc(result.error_message)}</div>` : '';
        html += `<div class="crv-detail" id="crv-det-${i}">
          ${errHtml}
          <div style="font-weight:600;color:var(--text-secondary,#444);margin-bottom:4px">Assertions</div>
          ${assertHtml}
          ${rawBody ? `<div style="font-weight:600;color:var(--text-secondary,#444);margin-top:8px;margin-bottom:4px">Response body</div>
          <pre class="crv-body">${_esc(preview)}</pre>` : ''}
        </div>`;
      }
    }

    rowsEl.innerHTML = html;

    rowsEl.querySelectorAll('.crv-row[data-i]').forEach(row => {
      const i   = parseInt(row.dataset.i, 10);
      const det = document.getElementById(`crv-det-${i}`);
      if (det) row.onclick = () => det.classList.toggle('open');
    });
  }

  async function _poll() {
    if (_destroyed) return;
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (!res.ok || !res.run) return;
      const run = res.run;
      if (!_startedAt) { _startedAt = run.started_at; _startElapsed(); }
      _updateHeader(run);
      _renderRows(run);
      if (run.status !== 'RUNNING') {
        if (_pollTimer)    { clearInterval(_pollTimer);    _pollTimer = null; }
        if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
      }
    } catch (e) { console.error('crv poll:', e); }
  }

  async function _init() {
    _renderShell();
    try {
      const colRes = await window.api('GET', `/collections/${collectionId}`);
      if (colRes.ok && colRes.collection?.requests) {
        _allRequests = colRes.collection.requests.slice()
          .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
      }
    } catch (_) {}
    await _poll();
    _pollTimer = setInterval(_poll, 1000);
  }

  _init();
}
