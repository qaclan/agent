function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showVariantComparisonModal(groups, collectionName, includeInDocs, organizeIntoFolders) {
  if (!groups?.length) {
    window._alertDialog('Nothing to group — no requests were provided.');
    return;
  }

  const state = groups.map((g, gi) => ({
    ...g,
    _gi: gi,
    action: g.default_action === 'keep_single' ? 'separate' : 'merge',
    included: g.variants.map(() => true),
    checkedFields: new Set(g.diff_fields.filter(f => f.checked_default).map(f => f.key)),
  }));

  function _groupHTML(g) {
    const rows = g.variants.map((v, vi) => `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;border-bottom:1px solid var(--border-subtle);font-size:12px;">
        <input type="checkbox" data-gi="${g._gi}" data-vi="${vi}" class="vcm-row-check" ${state[g._gi].included[vi] ? 'checked' : ''}>
        <span style="flex:1;font-family:var(--font-mono,monospace);color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${_esc(v.label_suggestion || v.request.name || `variant ${vi + 1}`)}
        </span>
        ${v.request.response_status ? `<span style="color:var(--text-muted);font-size:11px;">${_esc(String(v.request.response_status))}${v.request.duration_ms ? ` · ${v.request.duration_ms}ms` : ''}</span>` : ''}
        ${v.dup_count > 1 ? `<span class="badge badge-neutral" style="font-size:10px;">${v.dup_count - 1} dup${v.dup_count - 1 !== 1 ? 's' : ''} collapsed</span>` : ''}
      </div>`).join('');

    const fieldsHTML = g.needs_decision ? g.diff_fields.map(f => `
      <label style="display:flex;align-items:center;gap:6px;padding:3px 0 3px 24px;font-size:12px;cursor:pointer;">
        <input type="checkbox" data-gi="${g._gi}" data-field="${_esc(f.key)}" class="vcm-field-check" ${state[g._gi].checkedFields.has(f.key) ? 'checked' : ''}>
        <code style="font-family:var(--font-mono,monospace);color:var(--accent);">${_esc(f.field_name)}</code>
        <span style="color:var(--text-muted);">(${f.values.map(fv => _esc(String(fv ?? '—'))).join(' / ')}) &rarr; <code>{{${_esc(f.field_name)}}}</code></span>
      </label>`).join('') : '';

    const radioHTML = g.needs_decision ? `
      <div style="display:flex;gap:16px;padding:6px 8px;font-size:12px;">
        <label style="display:flex;align-items:center;gap:5px;cursor:pointer;">
          <input type="radio" name="vcm-action-${g._gi}" value="separate" class="vcm-action-radio" data-gi="${g._gi}" ${state[g._gi].action === 'separate' ? 'checked' : ''}>
          Keep as separate named requests
        </label>
        <label style="display:flex;align-items:center;gap:5px;cursor:pointer;">
          <input type="radio" name="vcm-action-${g._gi}" value="merge" class="vcm-action-radio" data-gi="${g._gi}" ${state[g._gi].action === 'merge' ? 'checked' : ''}>
          Merge into one parameterized request
        </label>
      </div>
      <div class="vcm-fields-${g._gi}" style="display:${state[g._gi].action === 'merge' ? '' : 'none'};">${fieldsHTML}</div>` : '';

    return `
      <div style="margin-bottom:14px;border:1px solid var(--border);border-radius:6px;overflow:hidden;">
        <div style="padding:6px 8px;background:var(--surface-2);font-size:12px;font-weight:600;">
          ${_esc(g.endpoint_label)} — ${g.variants.length} variant${g.variants.length !== 1 ? 's' : ''}${g.exact_dups_collapsed ? ` (${g.exact_dups_collapsed} exact dup${g.exact_dups_collapsed !== 1 ? 's' : ''} collapsed)` : ''}
        </div>
        <div>${rows}</div>
        ${radioHTML}
      </div>`;
  }

  function _render() {
    const listEl = document.getElementById('vcm-list');
    if (!listEl) return;
    listEl.innerHTML = state.map(_groupHTML).join('');

    listEl.querySelectorAll('.vcm-row-check').forEach(cb => cb.addEventListener('change', e => {
      const gi = Number(e.target.dataset.gi), vi = Number(e.target.dataset.vi);
      state[gi].included[vi] = e.target.checked;
    }));
    listEl.querySelectorAll('.vcm-action-radio').forEach(r => r.addEventListener('change', e => {
      const gi = Number(e.target.dataset.gi);
      state[gi].action = e.target.value;
      const fieldsEl = listEl.querySelector(`.vcm-fields-${gi}`);
      if (fieldsEl) fieldsEl.style.display = e.target.value === 'merge' ? '' : 'none';
    }));
    listEl.querySelectorAll('.vcm-field-check').forEach(cb => cb.addEventListener('change', e => {
      const gi = Number(e.target.dataset.gi), field = e.target.dataset.field;
      if (e.target.checked) state[gi].checkedFields.add(field);
      else state[gi].checkedFields.delete(field);
    }));
  }

  const modalBody = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px;">
      ${groups.length} endpoint group${groups.length !== 1 ? 's' : ''}. Resolve each group, then save.
    </p>
    <div id="vcm-list" style="max-height:480px;overflow-y:auto;"></div>`;

  window.showModal('Review Variants', modalBody, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Save', cls: 'btn-primary', action: async () => {
      const payloadGroups = state.map(g => ({
        endpoint_label: g.endpoint_label,
        action: g.action,
        checked_fields: Array.from(g.checkedFields),
        variants: g.variants.map((v, vi) => ({ request: v.request, included: g.included[vi] })),
      }));
      const data = await window.api('POST', '/discover/save-library', {
        groups: payloadGroups,
        collection_name: collectionName,
        include_in_docs: includeInDocs,
        organize_into_folders: organizeIntoFolders,
      });
      window.closeModal();
      if (data.ok) {
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${collectionName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
  ], null, 'lg');

  requestAnimationFrame(_render);
}
