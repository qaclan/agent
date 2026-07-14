/**
 * Shared {{var}} token extraction + exists/missing CSS styling for plain
 * <input> value fields. Used by key-value-table.js (headers/params/path-vars),
 * request-editor-view.js (auth fields, URL bar, scripts, body fallback),
 * assertion-builder.js, var-token-overlay.js, and json-editor.js.
 */

const _VAR_TOKEN_RE = /\{\{([^}]+)\}\}/g;

export function varTokensIn(value) {
  if (!value) return [];
  return [...value.matchAll(_VAR_TOKEN_RE)].map(m => m[1].trim());
}

export function tokenSpansIn(value) {
  if (!value) return [];
  const spans = [];
  _VAR_TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = _VAR_TOKEN_RE.exec(value)) !== null) {
    spans.push({ name: m[1].trim(), start: m.index, end: m.index + m[0].length });
  }
  return spans;
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function applyVarStyle(inp, knownNames) {
  const tokens = varTokensIn(inp.value);
  inp.classList.remove('kv-value--var-ok', 'kv-value--var-missing');
  if (!tokens.length || knownNames == null) return;
  const allKnown = tokens.every(name => knownNames.has(name));
  inp.classList.add(allKnown ? 'kv-value--var-ok' : 'kv-value--var-missing');
}
