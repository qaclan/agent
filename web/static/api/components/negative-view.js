/**
 * Shared negative-testing RESULT renderer.
 *
 * ONE source for every live surface: the editor Negative Testing result tab
 * (response-panel.js), the collection run detail (collection-run-view.js), and
 * the Runs history modal (app.js). The downloadable HTML report mirrors this
 * exact layout in cli/api_report.py::_render_negative — keep them in step.
 *
 * Loaded as a classic script (before app.js and the api module graph) so the
 * globals below are available to both module and non-module callers.
 *
 * window.qcNegativeCasesHtml(nr) -> headline + count chips + per-category
 *   outcome heatmap (all cases, compact) + a findings list of the failures with
 *   plain-words "should vs happened" messages.
 * window.qcNegativePill(nr)      -> compact pill for a collection-run / history row.
 *
 * Outcome is conveyed by a colored WORD (REJECTED / FALSE PASS / SERVER ERROR …)
 * and, in the grid, by the actual status code plus a color — never a bare glyph.
 */
(function () {
  'use strict';

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var CATEGORY_LABEL = {
    'input-validation': 'Input validation',
    'request-level': 'Request-level',
    'injection': 'Injection / fuzz'
  };
  var CAT_ORDER = ['input-validation', 'request-level', 'injection'];
  var CAT_COLOR = {
    'input-validation': 'var(--accent,#3b82f6)',
    'request-level': 'var(--warning,#f59e0b)',
    'injection': 'var(--danger,#ef4444)'
  };
  var CAT_CAPTION = {
    'input-validation': 'expects <b>4xx</b>',
    'request-level': 'each row own code',
    'injection': 'checks <b>no&nbsp;500&nbsp;·&nbsp;not&nbsp;reflected</b>'
  };
  // Short human labels for subtypes (columns in a grid, row name in the list).
  var SUB = {
    'missing-required': 'Missing', 'wrong-type': 'Wrong type', 'null': 'Null',
    'empty': 'Empty', 'boundary-min': 'Below min', 'boundary-max': 'Above max',
    'boundary-minlength': 'Too short', 'boundary-maxlength': 'Too long',
    'enum': 'Bad enum', 'format': 'Bad format', 'extra-field': 'Extra field',
    'oversized': 'Oversized', 'no-auth': 'No auth', 'garbage-token': 'Bad token',
    'wrong-method': 'Wrong method', 'wrong-content-type': 'Bad Content-Type',
    'unknown-route': 'Unknown route', 'malformed-json': 'Malformed JSON',
    'sqli': 'SQLi', 'xss': 'XSS', 'path-traversal': 'Traversal', 'null-byte': 'Null byte'
  };
  function subLabel(s) { return SUB[s] || s || ''; }
  function fieldName(t) {
    t = t || '';
    if (t.indexOf('body.') === 0) return { n: t.slice(5), k: 'Body field' };
    if (t.indexOf('param.') === 0) return { n: t.slice(6), k: 'Query param' };
    return { n: t, k: '' };
  }

  function is5xx(a) { return typeof a === 'number' && a >= 500; }

  // Display kind (color bucket) for a case outcome. g=rejected, r=critical/false-pass,
  // a=server-error/wrong-family (major), m=wrong-code (minor).
  function kind(c) {
    if (c.passed) return 'g';
    if (c.false_pass) return 'r';
    if (c.category === 'injection') return 'r';       // reflected or 5xx → critical
    if (c.severity === 'major') return 'a';
    if (c.severity === 'minor') return 'm';
    return 'r';
  }
  // The word shown on the chip / tag.
  function tagWord(c) {
    if (c.passed) return c.category === 'injection' ? 'SAFE' : 'REJECTED';
    if (c.false_pass) return 'FALSE PASS';
    if (c.category === 'injection') return c.reflected ? 'REFLECTED' : (is5xx(c.actual_status) ? 'SERVER ERROR' : 'FAILED');
    if (c.severity === 'major') return is5xx(c.actual_status) ? 'SERVER ERROR' : 'WRONG STATUS';
    if (c.severity === 'minor') return c.actual_status == null ? 'ERRORED' : 'WRONG CODE';
    return 'CRITICAL';
  }
  // Worst-first ordering for findings / the request-level list.
  function rankOf(c) {
    if (c.false_pass) return 0;
    if (!c.passed && c.severity === 'critical') return 1;
    if (!c.passed && c.severity === 'major') return 2;
    if (!c.passed && c.severity === 'minor') return 3;
    if (!c.passed) return 4;
    return 5;
  }

  var STYLE = '<style>'
    + '.qcn{line-height:1.5}'
    + '.qcn-skip{font-size:11px;color:var(--text-muted,#888)}'
    + '.qcn-head{display:flex;align-items:center;gap:10px;padding:10px 13px;border-radius:8px;margin-bottom:10px;border:1px solid}'
    + '.qcn-head.crit{background:var(--danger-bg,rgba(239,68,68,.13));border-color:var(--danger,#ef4444)}'
    + '.qcn-head.warn{background:var(--warning-bg,rgba(245,158,11,.13));border-color:var(--warning,#f59e0b)}'
    + '.qcn-head.ok{background:var(--success-bg,rgba(16,185,129,.13));border-color:var(--success,#10b981)}'
    + '.qcn-head__i{font-size:15px;flex:none}'
    + '.qcn-head__t{font-size:13px;font-weight:700}'
    + '.qcn-head.crit .qcn-head__t,.qcn-head.crit .qcn-head__i{color:var(--danger,#ef4444)}'
    + '.qcn-head.warn .qcn-head__t,.qcn-head.warn .qcn-head__i{color:var(--warning,#f59e0b)}'
    + '.qcn-head.ok .qcn-head__t,.qcn-head.ok .qcn-head__i{color:var(--success,#10b981)}'
    + '.qcn-head__s{margin-left:auto;font-size:11px;color:var(--text-secondary,#888);font-weight:500;white-space:nowrap}'
    + '.qcn-chips{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 10px}'
    + '.qcn-chip{font-size:10.5px;font-weight:600;padding:3px 9px;border-radius:999px;border:1px solid var(--border-default,rgba(128,128,128,.3))}'
    + '.qcn-chip b{font-variant-numeric:tabular-nums}'
    + '.qcn-chip.g{color:var(--success,#10b981)}.qcn-chip.r{color:var(--danger,#ef4444);border-color:var(--danger,#ef4444)}.qcn-chip.a{color:var(--warning,#f59e0b)}.qcn-chip.m{color:var(--text-secondary,#888)}'
    + '.qcn-legend{display:flex;gap:13px;flex-wrap:wrap;font-size:10px;color:var(--text-secondary,#888);margin:0 0 12px}'
    + '.qcn-sw{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:4px;vertical-align:middle}'
    + '.qcn-sw.g{background:var(--success,#10b981)}.qcn-sw.r{background:var(--danger,#ef4444)}.qcn-sw.a{background:var(--warning,#f59e0b)}.qcn-sw.m{background:var(--text-secondary,#888)}'
    + '.qcn-cat{margin-top:16px}'
    + '.qcn-cat__h{display:flex;align-items:center;gap:10px;margin:0 0 6px;padding-bottom:5px;border-bottom:1px solid var(--border-default,rgba(128,128,128,.2))}'
    + '.qcn-cat__dot{width:8px;height:8px;border-radius:2px;flex:none}'
    + '.qcn-cat__n{font-size:11.5px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:var(--text-primary,#eee)}'
    + '.qcn-cat__c{font-size:11px;color:var(--text-secondary,#888)}'
    + '.qcn-cat__e{margin-left:auto;font-size:10.5px;color:var(--text-primary,#eee);background:var(--accent-subtle,rgba(59,130,246,.1));border:1px solid var(--border-default,rgba(128,128,128,.2));border-radius:999px;padding:2px 10px;white-space:nowrap}'
    + '.qcn-cat__e b{color:var(--accent,#3b82f6);font-weight:700;font-family:var(--font-mono,monospace)}'
    + '.qcn-gridwrap{overflow-x:auto}'
    + '.qcn-grid{border-collapse:separate;border-spacing:0;width:100%;font-size:12px;table-layout:fixed}'
    + '.qcn-grid thead th{padding:5px 6px 7px;text-align:center;color:var(--text-secondary,#888);font-weight:600;font-size:9.5px;text-transform:uppercase;letter-spacing:.03em}'
    + '.qcn-grid thead th.qcn-tcol{text-align:left;width:150px}'
    + '.qcn-grid td{padding:2px 3px;vertical-align:middle}'
    + '.qcn-tgt__n{font-family:var(--font-mono,monospace);color:var(--text-primary,#eee);font-weight:600;font-size:12px}'
    + '.qcn-tgt__k{display:block;font-size:8.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted,#888);margin-top:1px}'
    + '.qcn-c{text-align:center}'
    + '.qcn-cell{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:30px;padding:3px 5px;border-radius:6px;border:1px solid transparent;font-family:var(--font-mono,monospace);font-weight:700;font-variant-numeric:tabular-nums;font-size:12px;line-height:1.15}'
    + '.qcn-cell small{font-size:8px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;opacity:.8;margin-top:1px}'
    + '.qcn-c-g{color:var(--success,#10b981);background:var(--success-bg,rgba(16,185,129,.1));border-color:var(--success-border,rgba(16,185,129,.28))}'
    + '.qcn-c-r{color:var(--danger,#ef4444);background:var(--danger-bg,rgba(239,68,68,.12));border-color:var(--danger-border,rgba(239,68,68,.3))}'
    + '.qcn-c-a{color:var(--warning,#f59e0b);background:var(--warning-bg,rgba(245,158,11,.12));border-color:var(--warning-border,rgba(245,158,11,.3))}'
    + '.qcn-c-m{color:var(--text-secondary,#888);background:var(--bg-elevated,rgba(128,128,128,.1));border-color:var(--border-default,rgba(128,128,128,.22))}'
    + '.qcn-c-na{color:var(--text-muted,#888);opacity:.4}'
    + '.qcn-find{display:flex;flex-direction:column;margin-top:2px}'
    + '.qcn-frow{display:flex;align-items:center;gap:10px;padding:4px 2px}'
    + '.qcn-ftag,.qcn-item__tag{flex:none;width:104px;text-align:center;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;padding:2px 0;border-radius:4px}'
    + '.qcn-ftag.g,.qcn-item__tag.g{color:var(--success,#10b981);background:var(--success-bg,rgba(16,185,129,.14))}'
    + '.qcn-ftag.r,.qcn-item__tag.r{color:var(--danger,#ef4444);background:var(--danger-bg,rgba(239,68,68,.15))}'
    + '.qcn-ftag.a,.qcn-item__tag.a{color:var(--warning,#f59e0b);background:var(--warning-bg,rgba(245,158,11,.15))}'
    + '.qcn-ftag.m,.qcn-item__tag.m{color:var(--text-secondary,#888);background:var(--bg-elevated,rgba(128,128,128,.1))}'
    + '.qcn-flbl{flex:none;font-family:var(--font-mono,monospace);font-size:11.5px;color:var(--text-primary,#eee)}'
    + '.qcn-flbl small{color:var(--text-muted,#888)}'
    + '.qcn-fmsg,.qcn-item__m{flex:1;min-width:0;font-size:11.5px;color:var(--text-secondary,#888)}'
    + '.qcn-list{display:flex;flex-direction:column}'
    + '.qcn-item{display:flex;align-items:center;gap:10px;padding:5px 8px;border-bottom:1px solid var(--border-subtle,rgba(128,128,128,.12));border-radius:5px}'
    + '.qcn-item.f{background:var(--danger-bg,rgba(239,68,68,.13))}'
    + '.qcn-item__n{font-weight:600;font-size:12px;color:var(--text-primary,#eee);min-width:150px}'
    + '</style>';

  function chip(k, label, n) {
    return '<span class="qcn-chip ' + k + '">' + label + ' <b>' + n + '</b></span>';
  }

  function cell(c) {
    if (!c) return '<td class="qcn-c"><span class="qcn-cell qcn-c-na" title="not applicable">·</span></td>';
    var code = c.actual_status == null ? '—' : c.actual_status;
    var sub = c.reflected ? '<small>refl</small>' : '';
    var tip = tagWord(c) + (c.note ? ' — ' + c.note : '');
    return '<td class="qcn-c"><span class="qcn-cell qcn-c-' + kind(c) + '" title="' + _esc(tip) + '">' + _esc(String(code)) + sub + '</span></td>';
  }

  function catHead(cat, list) {
    var rej = list.filter(function (c) { return c.passed; }).length;
    return '<div class="qcn-cat__h"><span class="qcn-cat__dot" style="background:' + CAT_COLOR[cat] + '"></span>'
      + '<span class="qcn-cat__n">' + _esc(CATEGORY_LABEL[cat] || cat) + '</span>'
      + '<span class="qcn-cat__c">' + rej + ' of ' + list.length + ' rejected</span>'
      + '<span class="qcn-cat__e">' + (CAT_CAPTION[cat] || '') + '</span></div>';
  }

  // Field × subtype outcome heatmap + a findings list beneath.
  function gridBlock(cat, list) {
    var subs = [], tgts = [], g = {};
    list.forEach(function (c) {
      if (subs.indexOf(c.subtype) < 0) subs.push(c.subtype);
      if (!g[c.target]) { g[c.target] = {}; tgts.push(c.target); }
      g[c.target][c.subtype] = c;
    });
    var h = '<div class="qcn-cat">' + catHead(cat, list)
      + '<div class="qcn-gridwrap"><table class="qcn-grid"><thead><tr><th class="qcn-tcol">Field</th>';
    subs.forEach(function (s) { h += '<th>' + _esc(subLabel(s)) + '</th>'; });
    h += '</tr></thead><tbody>';
    tgts.forEach(function (t) {
      var f = fieldName(t);
      h += '<tr><td><span class="qcn-tgt__n">' + _esc(f.n) + '</span>'
        + (f.k ? '<span class="qcn-tgt__k">' + _esc(f.k) + '</span>' : '') + '</td>';
      subs.forEach(function (s) { h += cell(g[t][s]); });
      h += '</tr>';
    });
    h += '</tbody></table></div></div>';
    return h;
  }

  // Independent cases (request-level) → a list, each with its outcome tag + message.
  function listBlock(cat, list) {
    var h = '<div class="qcn-cat">' + catHead(cat, list) + '<div class="qcn-list">';
    list.slice().sort(function (a, z) { return rankOf(a) - rankOf(z); }).forEach(function (c) {
      var fail = !c.passed;
      var msg = fail ? (c.note || '')
        : ('rejected correctly — got ' + (c.actual_status == null ? '—' : c.actual_status));
      h += '<div class="qcn-item' + (fail ? ' f' : '') + '">'
        + '<span class="qcn-item__n">' + _esc(subLabel(c.subtype) || fieldName(c.target).n) + '</span>'
        + '<span class="qcn-item__tag ' + kind(c) + '">' + tagWord(c) + '</span>'
        + '<span class="qcn-item__m">' + _esc(msg) + '</span></div>';
    });
    return h + '</div></div>';
  }

  function negativeCasesHtml(nr) {
    if (!nr || typeof nr !== 'object') return '';
    if (nr.verdict === 'skipped') {
      return '<div class="qcn-skip">Negative testing skipped ('
        + _esc(nr.skipped_reason || 'disabled') + ').</div>';
    }
    var cases = Array.isArray(nr.cases) ? nr.cases : [];
    if (!cases.length) return '';

    var total = cases.length, rej = 0, fp = 0, srv = 0, other = 0, critInj = 0;
    cases.forEach(function (c) {
      if (c.passed) { rej++; return; }
      if (c.false_pass) { fp++; return; }
      if (is5xx(c.actual_status)) srv++; else other++;
      if (c.category === 'injection' && (c.reflected || is5xx(c.actual_status))) critInj++;
    });

    var worst = nr.worst_severity || 'none';
    var hcls = worst === 'critical' ? 'crit' : (worst === 'none' ? 'ok' : 'warn');
    var htxt;
    if (fp) htxt = fp + ' false pass' + (fp > 1 ? 'es' : '') + ' — API accepted invalid input';
    else if (critInj) htxt = critInj + ' critical issue' + (critInj > 1 ? 's' : '') + ' on fuzzed input';
    else if (total - rej > 0) htxt = (total - rej) + ' returned the wrong status';
    else htxt = 'All ' + total + ' invalid inputs correctly rejected';
    var hicn = hcls === 'crit' ? '⛔' : (hcls === 'warn' ? '⚠' : '✓');

    var h = STYLE + '<div class="qcn">';
    h += '<div class="qcn-head ' + hcls + '"><span class="qcn-head__i">' + hicn + '</span>'
      + '<span class="qcn-head__t">' + _esc(htxt) + '</span>'
      + '<span class="qcn-head__s">' + rej + ' / ' + total + ' rejected</span></div>';
    h += '<div class="qcn-chips">' + chip('g', 'REJECTED', rej)
      + (fp ? chip('r', 'FALSE PASS', fp) : '')
      + (srv ? chip('a', 'SERVER ERROR', srv) : '')
      + (other ? chip('m', 'FAILED', other) : '') + '</div>';
    h += '<div class="qcn-legend">'
      + '<span><i class="qcn-sw g"></i>rejected</span>'
      + '<span><i class="qcn-sw r"></i>false pass / reflected</span>'
      + '<span><i class="qcn-sw a"></i>server error</span>'
      + '<span><i class="qcn-sw m"></i>wrong code</span>'
      + '<span>· = not applicable</span></div>';

    var byCat = {};
    cases.forEach(function (c) { (byCat[c.category] = byCat[c.category] || []).push(c); });
    CAT_ORDER.forEach(function (cat) {
      if (!byCat[cat]) return;
      h += cat === 'request-level' ? listBlock(cat, byCat[cat]) : gridBlock(cat, byCat[cat]);
    });
    Object.keys(byCat).forEach(function (cat) {
      if (CAT_ORDER.indexOf(cat) < 0) h += gridBlock(cat, byCat[cat]);
    });

    return h + '</div>';
  }

  function negativePill(nr) {
    if (!nr || nr.verdict === 'skipped') return '';
    var counts = nr.counts || {};
    if (!counts.total) return '';
    var worst = nr.worst_severity || 'none';
    var map = {
      critical: ['var(--danger,#ef4444)', 'rgba(239,68,68,.12)'],
      major: ['var(--warning,#f59e0b)', 'rgba(245,158,11,.12)'],
      minor: ['var(--text-secondary,#888)', 'rgba(136,136,136,.14)'],
      none: ['var(--success,#22c55e)', 'rgba(34,197,94,.12)']
    };
    var m = map[worst] || map.none;
    var fp = counts.false_pass || 0;
    var title = 'Negative testing — ' + (counts.passed || 0) + '/' + (counts.total || 0) + ' rejected'
      + (fp ? ', ' + fp + ' false-pass' : '');
    var lead = fp ? (fp + ' false-pass') : ('neg ' + (counts.passed || 0) + '/' + (counts.total || 0));
    return '<span title="' + _esc(title) + '" style="font-size:10px;padding:1px 6px;border-radius:3px;'
      + 'margin-left:6px;flex:none;background:' + m[1] + ';color:' + m[0] + ';white-space:nowrap">'
      + _esc(lead) + '</span>';
  }

  window.qcNegativeCasesHtml = negativeCasesHtml;
  window.qcNegativePill = negativePill;
})();
