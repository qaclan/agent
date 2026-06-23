import { createVarPicker } from './var-picker.js';

/**
 * createKeyValueTable(options) → { el, getRows, setRows }
 * options:
 *   placeholder?: { key, value }
 *   readOnly?: bool
 *   varPickerEnabled?: bool
 *   getVars?: async () => [{key, value, is_secret?, group?}]
 */
export function createKeyValueTable(options = {}) {
  const {
    placeholder = { key: 'Key', value: 'Value' },
    readOnly = false,
    varPickerEnabled = false,
    getVars = async () => [],
  } = options;

  const _picker = varPickerEnabled ? createVarPicker({ getVars }) : null;

  const wrapper = document.createElement('div');
  wrapper.className = 'kv-table-wrapper';

  const table = document.createElement('table');
  table.className = 'kv-table';
  table.innerHTML = `<thead><tr>
    <th style="width:32px"></th>
    <th>Key</th>
    <th>Value</th>
    ${varPickerEnabled && !readOnly ? '<th style="width:30px"></th>' : ''}
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
    addBtn.onclick = () => _addRow({});
    wrapper.appendChild(addBtn);
  }

  function _isVarRef(v) { return /\{\{[^}]+\}\}/.test(v || ''); }

  function _applyVarStyle(inp) {
    inp.classList.toggle('kv-value--var-ref', _isVarRef(inp.value));
  }

  function _handleAutocomplete(inp) {
    const val = inp.value;
    const caret = inp.selectionStart ?? val.length;
    const before = val.slice(0, caret);
    const openAt = before.lastIndexOf('{{');
    if (openAt !== -1 && !before.slice(openAt).includes('}}')) {
      const partial = before.slice(openAt + 2);
      _picker.open(inp, (varToken) => {
        const after = val.slice(caret);
        inp.value = val.slice(0, openAt) + varToken + after;
        const newPos = openAt + varToken.length;
        inp.setSelectionRange(newPos, newPos);
        inp.dispatchEvent(new Event('input'));
      }, partial);
    } else {
      _picker.close();
    }
  }

  function _addRow(data = {}) {
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
    _applyVarStyle(valInput);
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      valInput.addEventListener('input', () => {
        _applyVarStyle(valInput);
        if (varPickerEnabled) _handleAutocomplete(valInput);
      });
    }

    if (varPickerEnabled && !readOnly) {
      const pickerTd = document.createElement('td');
      const pickerBtn = document.createElement('button');
      pickerBtn.type = 'button';
      pickerBtn.title = 'Insert variable';
      pickerBtn.style.cssText = 'background:none;border:1px solid var(--border);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:10px;color:var(--text-muted);line-height:1.4;';
      pickerBtn.textContent = '{}';
      pickerBtn.onclick = () => {
        _picker.open(pickerBtn, (varToken) => {
          valInput.value = varToken;
          valInput.dispatchEvent(new Event('input'));
        });
      };
      pickerTd.appendChild(pickerBtn);
      tr.appendChild(pickerTd);
    }

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
