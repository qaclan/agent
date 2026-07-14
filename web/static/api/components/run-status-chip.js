/**
 * mountRunStatusChip(container, { getCurrentViewedRunId, onJump }) -> { update, refresh }
 * Renders a pill in `container` for any RUNNING collection run other than
 * the one the user is currently viewing (getCurrentViewedRunId()). Hidden
 * when there's nothing to show. Click jumps to the run via onJump.
 */
export function mountRunStatusChip(container, { getCurrentViewedRunId, onJump }) {
  let _runs = [];
  let _dropdownOpen = false;

  const chip = document.createElement('div');
  chip.id = 'run-status-chip';
  chip.style.cssText = 'position:relative;display:none;align-items:center;gap:6px;' +
    'padding:4px 10px;border-radius:14px;background:var(--warning-bg);' +
    'border:1px solid var(--warning);font-size:11px;font-weight:600;' +
    'color:var(--warning);cursor:pointer;white-space:nowrap;user-select:none;';
  container.appendChild(chip);

  const label = document.createElement('span');
  chip.appendChild(label);

  const dropdown = document.createElement('div');
  dropdown.style.cssText = 'position:absolute;top:calc(100% + 4px);right:0;' +
    'background:var(--bg-elevated);border:1px solid var(--border-strong);' +
    'border-radius:8px;box-shadow:var(--shadow-md);min-width:220px;display:none;' +
    'z-index:50;overflow:hidden;';
  chip.appendChild(dropdown);

  function _esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _doneCount(r) {
    return (r.passed || 0) + (r.failed || 0) + (r.error_count || 0);
  }

  function _render() {
    const viewedId = getCurrentViewedRunId ? getCurrentViewedRunId() : null;
    const visible = _runs.filter(r => r.id !== viewedId);

    if (!visible.length) {
      chip.style.display = 'none';
      dropdown.style.display = 'none';
      _dropdownOpen = false;
      return;
    }
    chip.style.display = 'inline-flex';

    if (visible.length === 1) {
      const r = visible[0];
      label.textContent = `● Running: ${r.collection_name} ${_doneCount(r)}/${r.total || 0}`;
      dropdown.style.display = 'none';
      dropdown.innerHTML = '';
      chip.onclick = () => onJump(r.id, r.collection_id, r.collection_name);
      return;
    }

    label.textContent = `● ${visible.length} running ▾`;
    dropdown.innerHTML = visible.map(r => `
      <div class="rsc-row" data-run-id="${_esc(r.id)}" data-col-id="${_esc(r.collection_id)}" data-col-name="${_esc(r.collection_name)}"
        style="padding:8px 12px;font-size:12px;font-weight:500;color:var(--text-primary);cursor:pointer;border-bottom:1px solid var(--border-subtle);">
        ${_esc(r.collection_name)}
        <span style="color:var(--text-muted);font-weight:400;"> ${_doneCount(r)}/${r.total || 0}</span>
      </div>`).join('');

    dropdown.querySelectorAll('.rsc-row').forEach(row => {
      row.onmouseenter = () => { row.style.background = 'var(--bg-panel)'; };
      row.onmouseleave = () => { row.style.background = ''; };
      row.onclick = (e) => {
        e.stopPropagation();
        onJump(row.dataset.runId, row.dataset.colId, row.dataset.colName);
      };
    });

    dropdown.style.display = _dropdownOpen ? 'block' : 'none';
    chip.onclick = (e) => {
      if (dropdown.contains(e.target)) return;
      _dropdownOpen = !_dropdownOpen;
      dropdown.style.display = _dropdownOpen ? 'block' : 'none';
    };
  }

  document.addEventListener('click', (e) => {
    if (_dropdownOpen && !chip.contains(e.target)) {
      _dropdownOpen = false;
      dropdown.style.display = 'none';
    }
  });

  function update(runs) { _runs = runs || []; _render(); }
  function refresh() { _render(); }

  return { update, refresh };
}
