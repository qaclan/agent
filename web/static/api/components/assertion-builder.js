/**
 * createAssertionBuilder() → { el, getAssertions, setAssertions }
 * Assertion shape: {type, path?, key?, op, value}
 */
export function createAssertionBuilder() {
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
    header:        ['eq', 'ne', 'contains', 'exists', 'not_exists'],
    response_time: ['lt', 'gt', 'eq'],
    body_text:     ['contains', 'eq', 'matches'],
  };

  const OP_LABELS = {
    eq: '= equals', ne: '≠ not equals', lt: '< less than', gt: '> greater than',
    contains: '⊃ contains', exists: '∃ exists', not_exists: '∄ not exists', matches: '~ matches regex',
  };

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
    extraInput.className = 'assertion-extra input-sm';
    extraInput.placeholder = '$.path or header-key';
    extraInput.value = data.path || data.key || '';
    row.appendChild(extraInput);

    // Operator select
    const opSelect = document.createElement('select');
    opSelect.className = 'assertion-op input-sm';
    row.appendChild(opSelect);

    // Value input
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'assertion-value input-sm';
    valInput.placeholder = 'expected value';
    valInput.value = data.value !== undefined ? String(data.value) : '';
    row.appendChild(valInput);

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
    delBtn.textContent = '×';
    delBtn.onclick = () => row.remove();
    row.appendChild(delBtn);

    function _updateUI() {
      const t = typeSelect.value;
      const ops = TYPE_OPS[t] || ['eq'];

      // Rebuild op options
      opSelect.innerHTML = '';
      ops.forEach(op => {
        const opt = document.createElement('option');
        opt.value = op;
        opt.textContent = OP_LABELS[op] || op;
        opSelect.appendChild(opt);
      });
      if (data.op && ops.includes(data.op)) opSelect.value = data.op;

      // Show/hide extra input
      const needsExtra = (t === 'json_path' || t === 'header');
      extraInput.style.display = needsExtra ? '' : 'none';
      extraInput.placeholder = t === 'json_path' ? '$.path' : 'Header-Name';

      // Show/hide value (exists/not_exists don't need it)
      const op = opSelect.value;
      valInput.style.display = (op === 'exists' || op === 'not_exists') ? 'none' : '';
    }

    typeSelect.onchange = _updateUI;
    opSelect.onchange = _updateUI;
    _updateUI();

    list.appendChild(row);
    return row;
  }

  function getAssertions() {
    const results = [];
    list.querySelectorAll('.assertion-row').forEach(row => {
      const type = row.querySelector('.assertion-type').value;
      const op = row.querySelector('.assertion-op').value;
      const value = row.querySelector('.assertion-value').value;
      const extra = row.querySelector('.assertion-extra').value.trim();
      const assertion = { type, op };
      if (op !== 'exists' && op !== 'not_exists') {
        const parsed = isNaN(value) ? value : Number(value);
        assertion.value = parsed;
      }
      if (type === 'json_path' && extra) assertion.path = extra;
      if (type === 'header' && extra) assertion.key = extra;
      results.push(assertion);
    });
    return results;
  }

  function setAssertions(assertions = []) {
    list.innerHTML = '';
    assertions.forEach(a => _addRow(a));
  }

  return { el: wrapper, getAssertions, setAssertions };
}
