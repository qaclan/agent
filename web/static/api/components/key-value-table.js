import { createVarPicker } from './var-picker.js';
import { createInlineVarDrop } from './inline-var-drop.js';
import { applyVarStyle } from './var-style.js';

/**
 * createKeyValueTable(options) → { el, getRows, setRows }
 * options:
 *   placeholder?: { key, value }
 *   readOnly?: bool
 *   varPickerEnabled?: bool
 *   getVars?: async () => [{key, value, is_secret?, group?}]
 *   fileFieldsEnabled?: bool — adds a per-row "attach file" control; rows with
 *     an attached file report {filename, content_type, is_file: true, value: base64}
 */
export function createKeyValueTable(options = {}) {
  const {
    placeholder = { key: 'Key', value: 'Value' },
    readOnly = false,
    varPickerEnabled = false,
    getVars = async () => [],
    fileFieldsEnabled = false,
    getKnownVarNames = null,
  } = options;

  function _fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  function _formatSize(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  const _picker = varPickerEnabled ? createVarPicker({ getVars }) : null;
  const _inlineDrop = varPickerEnabled ? createInlineVarDrop(getVars) : null;

  const wrapper = document.createElement('div');
  wrapper.className = 'kv-table-wrapper';

  const table = document.createElement('table');
  table.className = 'kv-table';
  table.innerHTML = `<thead><tr>
    <th style="width:32px"></th>
    <th>Key</th>
    <th>Value</th>
    ${varPickerEnabled && !readOnly ? '<th style="width:30px"></th>' : ''}
    ${fileFieldsEnabled && !readOnly ? '<th style="width:32px"></th>' : ''}
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

  function _styleValueInput(inp) {
    if (getKnownVarNames) applyVarStyle(inp, getKnownVarNames());
    else _applyVarStyle(inp);
  }

  function _setFileState(tr, valInput, meta) {
    tr._fileMeta = meta; // null, or {filename, content_type, base64, size}
    if (meta) {
      valInput.value = meta.size != null ? `📎 ${meta.filename} (${_formatSize(meta.size)})` : `📎 ${meta.filename}`;
      valInput.readOnly = true;
      valInput.classList.add('kv-value--file');
    } else {
      valInput.readOnly = readOnly;
      valInput.classList.remove('kv-value--file');
      if (valInput.value.startsWith('📎 ')) valInput.value = '';
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
    _styleValueInput(valInput);
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      valInput.addEventListener('input', () => _styleValueInput(valInput));
      if (varPickerEnabled) _inlineDrop.watchInput(valInput);
    }

    if (varPickerEnabled && !readOnly) {
      const pickerTd = document.createElement('td');
      const pickerBtn = document.createElement('button');
      pickerBtn.type = 'button';
      pickerBtn.title = 'Insert variable';
      pickerBtn.style.cssText = 'background:none;border:1px solid var(--border-default);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:10px;color:var(--text-muted);line-height:1.4;';
      pickerBtn.textContent = '{}';
      pickerBtn.onclick = () => {
        _picker.open(pickerBtn, (varToken) => {
          valInput.value = varToken;
          valInput.dispatchEvent(new Event('input'));
          valInput.focus();
        });
      };
      pickerTd.appendChild(pickerBtn);
      tr.appendChild(pickerTd);
    }

    if (fileFieldsEnabled && !readOnly) {
      const fileTd = document.createElement('td');
      const fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.style.display = 'none';

      const fileBtn = document.createElement('button');
      fileBtn.type = 'button';
      fileBtn.className = 'btn btn-xs btn-ghost';
      fileBtn.style.cssText = 'background:none;border:1px solid var(--border-default);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:11px;color:var(--text-muted);line-height:1.4;';

      function _refreshFileBtn() {
        const attached = !!tr._fileMeta;
        fileBtn.textContent = attached ? '✕' : '📎';
        fileBtn.title = attached ? 'Remove attached file' : 'Attach file';
      }

      fileBtn.onclick = () => {
        if (tr._fileMeta) {
          _setFileState(tr, valInput, null);
          _refreshFileBtn();
        } else {
          fileInput.click();
        }
      };
      fileInput.addEventListener('change', async () => {
        const file = fileInput.files && fileInput.files[0];
        fileInput.value = '';
        if (!file) return;
        const base64 = await _fileToBase64(file);
        _setFileState(tr, valInput, {
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
          base64,
          size: file.size,
        });
        _refreshFileBtn();
      });

      if (data.is_file && data.filename) {
        _setFileState(tr, valInput, {
          filename: data.filename,
          content_type: data.content_type,
          base64: data.value || '',
          size: null,
        });
      }
      _refreshFileBtn();

      fileTd.appendChild(fileBtn);
      fileTd.appendChild(fileInput);
      tr.appendChild(fileTd);
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
      const enabledCb = tr.querySelector('.kv-enabled');
      const enabled = enabledCb ? enabledCb.checked : true;
      if (!key) return;
      if (fileFieldsEnabled && tr._fileMeta) {
        const row = {
          key, enabled,
          value: tr._fileMeta.base64 || '',
          filename: tr._fileMeta.filename,
          is_file: true,
        };
        if (tr._fileMeta.content_type) row.content_type = tr._fileMeta.content_type;
        rows.push(row);
      } else {
        const value = tr.querySelector('.kv-value')?.value || '';
        rows.push({ key, value, enabled });
      }
    });
    return rows;
  }

  function setRows(rows = []) {
    tbody.innerHTML = '';
    rows.forEach(r => _addRow(r));
  }

  function restyleAll() {
    tbody.querySelectorAll('.kv-value').forEach(_styleValueInput);
  }

  return { el: wrapper, getRows, setRows, restyleAll };
}
