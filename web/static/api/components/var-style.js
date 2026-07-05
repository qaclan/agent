/**
 * Shared {{var}} token extraction + exists/missing CSS styling for plain
 * <input> value fields. Used by key-value-table.js (headers/params/path-vars)
 * and request-editor-view.js (auth fields) — NOT by the body editor or
 * script textareas.
 */

const _VAR_TOKEN_RE = /\{\{([^}]+)\}\}/g;

export function varTokensIn(value) {
  if (!value) return [];
  return [...value.matchAll(_VAR_TOKEN_RE)].map(m => m[1].trim());
}

export function applyVarStyle(inp, knownNames) {
  const tokens = varTokensIn(inp.value);
  inp.classList.remove('kv-value--var-ok', 'kv-value--var-missing');
  if (!tokens.length || knownNames == null) return;
  const allKnown = tokens.every(name => knownNames.has(name));
  inp.classList.add(allKnown ? 'kv-value--var-ok' : 'kv-value--var-missing');
}
