/**
 * createAssertionBuilder(options?) → { el, getAssertions, setAssertions, restyleAll }
 * options.getVarsList?: () => Array<{key, value, group?}>|null — when provided,
 * the path/expected-value inputs get per-token {{var}} coloring + hover
 * tooltip, and the expected-value input additionally gets the whole-field
 * kv-value--var-ok/--missing bg tint.
 * Assertion shape: {type, path?, key?, op, value, matchMode?}
 * matchMode ('first'|'any'|'all', json_path only, default 'first') — which of
 * possibly-multiple JSONPath matches (wildcard/recursive-descent paths) must
 * satisfy the op. Omitted when 'first' to keep old assertion JSON valid.
 */
import { attachTokenOverlay } from './var-token-overlay.js';
import { applyVarStyle } from './var-style.js';

export function createAssertionBuilder(options = {}) {
  const { getVarsList = null } = options;
  const _overlays = [];
  let _hasInvalid = false;
  const wrapper = document.createElement('div');
  wrapper.className = 'assertion-builder';

  const list = document.createElement('div');
  list.className = 'assertion-list';
  wrapper.appendChild(list);

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'btn btn-xs btn-ghost';
  addBtn.style.marginTop = '6px';
  addBtn.textContent = '+ Add Assertion';
  addBtn.onclick = () => _addRow({});
  wrapper.appendChild(addBtn);

  const TYPE_OPS = {
    status:        ['eq', 'ne', 'lt', 'gt'],
    json_path:     ['eq', 'ne', 'lt', 'gt', 'contains', 'exists', 'not_exists', 'matches'],
    header:        ['eq', 'ne', 'contains', 'exists', 'not_exists', 'matches'],
    response_time: ['lt', 'gt', 'eq'],
    body_text:     ['contains', 'eq', 'matches'],
  };

  const OP_LABELS = {
    eq: '= equals', ne: '≠ not equals', lt: '< less than', gt: '> greater than',
    contains: '⊃ contains', exists: '∃ exists', not_exists: '∄ not exists', matches: '~ matches regex',
  };

  const MATCH_MODE_LABELS = { first: 'first match', any: 'any match', all: 'all matches' };

  function _addRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'assertion-row';

    // Type select
    const typeSelect = document.createElement('select');
    typeSelect.className = 'assertion-type input-sm';
    ['status', 'json_path', 'header', 'response_time', 'body_text'].forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeSelect.appendChild(opt);
    });
    typeSelect.value = data.type || 'status';
    row.appendChild(typeSelect);

    // Dynamic path/key field (shown for json_path and header)
    const extraInput = document.createElement('input');
    extraInput.type = 'text';
    extraInput.autocomplete = 'off';
    extraInput.className = 'assertion-extra input-sm';
    extraInput.placeholder = '$.path or header-key';
    extraInput.value = data.path || data.key || '';
    let extraOverlay = null;
    if (getVarsList) {
      extraOverlay = attachTokenOverlay(extraInput, getVarsList);
      _overlays.push(extraOverlay);
      row.appendChild(extraOverlay.el);
    } else {
      row.appendChild(extraInput);
    }

    // Operator select
    const opSelect = document.createElement('select');
    opSelect.className = 'assertion-op input-sm';
    row.appendChild(opSelect);

    // Match mode select (json_path only) — which of possibly-multiple
    // JSONPath matches (wildcard/recursive-descent paths) must satisfy the op.
    const matchModeSelect = document.createElement('select');
    matchModeSelect.className = 'assertion-matchmode input-sm';
    matchModeSelect.title = 'Which JSONPath match(es) must satisfy the operator — relevant for wildcard/recursive-descent paths that can match more than one node.';
    Object.entries(MATCH_MODE_LABELS).forEach(([mode, label]) => {
      const opt = document.createElement('option');
      opt.value = mode;
      opt.textContent = label;
      matchModeSelect.appendChild(opt);
    });
    matchModeSelect.value = data.matchMode || 'first';
    row.appendChild(matchModeSelect);

    // Value input
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.autocomplete = 'off';
    valInput.className = 'assertion-value input-sm';
    valInput.placeholder = 'expected value';
    valInput.value = data.value !== undefined ? String(data.value) : '';
    function _styleValInput() {
      if (getVarsList) applyVarStyle(valInput, new Set((getVarsList() || []).map(v => v.key)));
    }
    _styleValInput();
    let valOverlay = null;
    if (getVarsList) {
      valInput.addEventListener('input', _styleValInput);
      valOverlay = attachTokenOverlay(valInput, getVarsList);
      _overlays.push(valOverlay);
      row.appendChild(valOverlay.el);
    } else {
      row.appendChild(valInput);
    }

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
    delBtn.textContent = '×';
    delBtn.onclick = () => row.remove();
    row.appendChild(delBtn);

    // Rebuilding <option>s on every change (including the op select's own
    // change) used to reset selectedIndex back to 0 mid-interaction — picking
    // any op other than the first ('eq') would immediately snap back to it.
    // Only rebuild the option list on a type change; an op change just
    // toggles field visibility against the already-selected value.
    function _rebuildOps() {
      const t = typeSelect.value;
      const ops = TYPE_OPS[t] || ['eq'];
      const prevOp = opSelect.value || data.op;
      opSelect.innerHTML = '';
      ops.forEach(op => {
        const opt = document.createElement('option');
        opt.value = op;
        opt.textContent = OP_LABELS[op] || op;
        opSelect.appendChild(opt);
      });
      opSelect.value = ops.includes(prevOp) ? prevOp : ops[0];
    }

    function _syncVisibility() {
      const t = typeSelect.value;
      const op = opSelect.value;
      const needsValue = op !== 'exists' && op !== 'not_exists';

      // Show/hide extra input (toggle the overlay wrap when present, not the
      // inner input directly — the sibling overlay div isn't hidden by the
      // input's own display:none, so it must be the thing that's toggled)
      const needsExtra = (t === 'json_path' || t === 'header');
      (extraOverlay ? extraOverlay.el : extraInput).style.display = needsExtra ? '' : 'none';
      extraInput.placeholder = t === 'json_path' ? '$.path' : 'Header-Name';

      // Match mode only means anything for json_path with a value-bearing op —
      // exists/not_exists already check "any node matched" regardless of mode.
      matchModeSelect.style.display = (t === 'json_path' && needsValue) ? '' : 'none';

      // Show/hide value (exists/not_exists don't need it)
      (valOverlay ? valOverlay.el : valInput).style.display = needsValue ? '' : 'none';
      if (!needsValue) valInput.classList.remove('assertion-value--invalid');
    }

    function _validateValue() {
      const needsValue = opSelect.value !== 'exists' && opSelect.value !== 'not_exists';
      const blank = needsValue && valInput.value.trim() === '';
      valInput.classList.toggle('assertion-value--invalid', blank);
      return !blank;
    }

    function _updateUI() { _rebuildOps(); _syncVisibility(); _validateValue(); }

    typeSelect.onchange = _updateUI;
    opSelect.onchange = () => { _syncVisibility(); _validateValue(); };
    valInput.addEventListener('input', _validateValue);
    _updateUI();

    list.appendChild(row);
    return row;
  }

  // Reads whatever value is currently typed. No numeric coercion here — a
  // zero-padded string ("00501") or a very large integer ID must survive as
  // the exact text the user typed; the backend does its own numeric casts
  // (int()/float() both accept numeral strings) where an op needs them, and
  // stays type-aware for eq/ne (see _values_equal in cli/api_runner.py).
  function getAssertions() {
    const results = [];
    let hasError = false;
    list.querySelectorAll('.assertion-row').forEach(row => {
      const type = row.querySelector('.assertion-type').value;
      const op = row.querySelector('.assertion-op').value;
      const valInput = row.querySelector('.assertion-value');
      const extra = row.querySelector('.assertion-extra').value.trim();
      const needsValue = op !== 'exists' && op !== 'not_exists';
      const blank = needsValue && valInput.value.trim() === '';
      valInput.classList.toggle('assertion-value--invalid', blank);
      if (blank) { hasError = true; return; }
      const assertion = { type, op };
      if (needsValue) assertion.value = valInput.value;
      if (type === 'json_path' && extra) assertion.path = extra;
      if (type === 'header' && extra) assertion.key = extra;
      if (type === 'json_path' && needsValue) {
        const matchMode = row.querySelector('.assertion-matchmode').value;
        if (matchMode !== 'first') assertion.matchMode = matchMode;
      }
      results.push(assertion);
    });
    _hasInvalid = hasError;
    return results;
  }

  function hasInvalidAssertions() {
    return _hasInvalid;
  }

  function setAssertions(assertions = []) {
    list.innerHTML = '';
    _overlays.length = 0;
    assertions.forEach(a => _addRow(a));
  }

  function restyleAll() {
    _overlays.forEach(o => o.refresh());
    if (getVarsList) {
      const known = new Set((getVarsList() || []).map(v => v.key));
      list.querySelectorAll('.assertion-value').forEach(inp => applyVarStyle(inp, known));
    }
  }

  return { el: wrapper, getAssertions, setAssertions, restyleAll, hasInvalidAssertions };
}
