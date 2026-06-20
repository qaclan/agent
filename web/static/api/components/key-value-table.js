/**
 * createKeyValueTable(options) → { el, getRows, setRows }
 * options: { placeholder?: { key, value }, readOnly?: bool }
 * getRows() → [{key, value, enabled}]
 * setRows(rows)
 */
export function createKeyValueTable(options = {}) {
  const { placeholder = { key: 'Key', value: 'Value' }, readOnly = false } = options;

  const wrapper = document.createElement('div');
  wrapper.className = 'kv-table-wrapper';

  const table = document.createElement('table');
  table.className = 'kv-table';
  table.innerHTML = `<thead><tr>
    <th style="width:32px"></th>
    <th>Key</th>
    <th>Value</th>
    ${readOnly ? '' : '<th style="width:32px"></th>'}
  </tr></thead>`;
  const tbody = document.createElement('tbody');
  table.appendChild(tbody);
  wrapper.appendChild(table);

  if (!readOnly) {
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-xs btn-ghost';
    addBtn.style.marginTop = '6px';
    addBtn.textContent = '+ Add Row';
    addBtn.onclick = () => _addRow({}, true);
    wrapper.appendChild(addBtn);
  }

  function _addRow(data = {}, enabled = true) {
    const tr = document.createElement('tr');
    tr.className = 'kv-row';

    const enabledTd = document.createElement('td');
    if (!readOnly) {
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = data.enabled !== false;
      cb.className = 'kv-enabled';
      enabledTd.appendChild(cb);
    }
    tr.appendChild(enabledTd);

    const keyTd = document.createElement('td');
    const keyInput = document.createElement('input');
    keyInput.type = 'text';
    keyInput.className = 'kv-key input-sm';
    keyInput.placeholder = placeholder.key;
    keyInput.value = data.key || '';
    keyInput.readOnly = readOnly;
    keyTd.appendChild(keyInput);
    tr.appendChild(keyTd);

    const valTd = document.createElement('td');
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'kv-value input-sm';
    valInput.placeholder = placeholder.value;
    valInput.value = data.value || '';
    valInput.readOnly = readOnly;
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      const delTd = document.createElement('td');
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
      delBtn.textContent = '×';
      delBtn.onclick = () => tr.remove();
      delTd.appendChild(delBtn);
      tr.appendChild(delTd);
    }

    tbody.appendChild(tr);
    return tr;
  }

  function getRows() {
    const rows = [];
    tbody.querySelectorAll('tr.kv-row').forEach(tr => {
      const key = tr.querySelector('.kv-key')?.value?.trim() || '';
      const value = tr.querySelector('.kv-value')?.value || '';
      const enabledCb = tr.querySelector('.kv-enabled');
      const enabled = enabledCb ? enabledCb.checked : true;
      if (key) rows.push({ key, value, enabled });
    });
    return rows;
  }

  function setRows(rows = []) {
    tbody.innerHTML = '';
    rows.forEach(r => _addRow(r));
  }

  return { el: wrapper, getRows, setRows };
}
