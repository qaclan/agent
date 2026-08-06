/**
 * Shared response-schema drift renderer — Option A (plain-words, grouped, dense).
 *
 * ONE source for every live surface: the editor Schema Diff tab
 * (response-panel.js), the collection run detail (collection-run-view.js), and
 * the Runs history modal (app.js). The downloadable HTML report mirrors this
 * exact layout in cli/api_report.py::_render_schema_drift — keep them in step.
 *
 * Loaded as a classic script (before app.js and the api module graph) so the
 * globals below are available to both module and non-module callers.
 *
 * window.qcSchemaDiffHtml(drift)  -> grouped changes block (Breaking then Added)
 * window.qcSchemaDriftPill(drift) -> compact "schema Δ N" pill for a row
 */
(function () {
  'use strict';

  var DANGER = 'var(--danger,#ef4444)';
  var WARNING = 'var(--warning,#f59e0b)';
  var MUTED = 'var(--text-muted,#888)';

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Verb glyph: what happened to the field.
  function _sign(kind) {
    if (kind === 'removed') return '−'; // −
    if (kind === 'added') return '+';
    return '~'; // type-changed / became-nullable / element-type-changed
  }

  // Right-hand type note. Removed shows the lost type, added shows the new type,
  // a type change shows "old → new". No ∅/arrow-to-nothing noise.
  function _typeText(d) {
    var from = d.expected_type == null ? '' : String(d.expected_type);
    var to = d.actual_type == null ? '' : String(d.actual_type);
    if (d.kind === 'removed') return from;
    if (d.kind === 'added') return to;
    return (from || '?') + ' → ' + (to || 'null');
  }

  function _row(d, color) {
    return '<div style="display:flex;align-items:baseline;gap:8px;padding:1px 0;'
      + 'font-family:var(--font-mono,monospace);font-size:12px">'
      + '<span style="color:' + color + ';flex:none;width:10px;text-align:center;'
      + 'font-weight:700">' + _sign(d.kind) + '</span>'
      + '<span style="flex:1;min-width:0;word-break:break-all">' + _esc(d.path) + '</span>'
      + '<span style="color:' + MUTED + ';font-size:11px;flex:none;white-space:nowrap">'
      + _esc(_typeText(d)) + '</span>'
      + '</div>';
  }

  function _group(label, color, rows) {
    if (!rows.length) return '';
    return '<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
      + 'letter-spacing:.05em;color:' + color + ';margin:8px 0 2px">' + label + '</div>'
      + rows.join('');
  }

  function schemaDiffHtml(drift) {
    if (!drift || typeof drift !== 'object') return '';
    var diffs = Array.isArray(drift.differences) ? drift.differences : [];
    if (!diffs.length) return '';
    var breaking = [], added = [];
    diffs.forEach(function (d) {
      if (d.severity === 'breaking') breaking.push(_row(d, DANGER));
      else added.push(_row(d, WARNING));
    });
    var brk = drift.breaking_count || breaking.length;
    var add = drift.additive_count || added.length;
    var parts = [];
    if (brk) parts.push(brk + ' breaking');
    if (add) parts.push(add + ' added');
    var summary = '<div style="font-size:11px;color:' + MUTED + ';margin-bottom:2px">'
      + 'Schema changed — ' + parts.join(', ') + '</div>';
    return '<div class="qc-sdiff" style="line-height:1.5">' + summary
      + _group('Breaking', DANGER, breaking)
      + _group('Added', WARNING, added)
      + '</div>';
  }

  function schemaDriftPill(drift) {
    if (!drift || !Array.isArray(drift.differences) || !drift.differences.length) return '';
    var brk = drift.breaking_count || 0;
    var color = brk ? DANGER : WARNING;
    var bg = brk ? 'rgba(239,68,68,.12)' : 'rgba(245,158,11,.12)';
    return '<span title="Response schema drift" style="font-size:10px;padding:1px 6px;'
      + 'border-radius:3px;margin-left:6px;flex:none;background:' + bg + ';color:' + color
      + ';white-space:nowrap">schema Δ ' + drift.differences.length + '</span>';
  }

  window.qcSchemaDiffHtml = schemaDiffHtml;
  window.qcSchemaDriftPill = schemaDriftPill;
})();
