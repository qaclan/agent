// Pure, DOM-free curl string builder. No imports — callers resolve
// {authType, authConfig} (never 'inherit') before calling.

const SENSITIVE_HEADER_RE = /(password|secret|token|authorization|api[-_]?key|auth)/i;
const VAR_RE = /\{\{[^}]+\}\}/;

function _shQuote(str) {
  return `'${String(str).replace(/'/g, "'\\''")}'`;
}

function _maskValue(key, value) {
  if (/^cookie$/i.test(key)) {
    return value
      .split(';')
      .map(pair => {
        const [k, v = ''] = pair.trim().split('=');
        return v.length <= 4 ? `${k}=***` : `${k}=${v.slice(0, 2)}***${v.slice(-2)}`;
      })
      .join('; ');
  }
  const schemeMatch = value.match(/^(Bearer|Basic|Digest)\s+/i);
  if (schemeMatch) return `${schemeMatch[1]} ***REDACTED***`;
  return '***REDACTED***';
}

function _redactHeaders(headers, reveal) {
  if (reveal) return headers;
  return headers.map(h => {
    if (SENSITIVE_HEADER_RE.test(h.key) && !VAR_RE.test(h.value)) {
      return { ...h, value: _maskValue(h.key, h.value) };
    }
    return h;
  });
}

function _encodeQueryValue(v) {
  return VAR_RE.test(v) ? v : encodeURIComponent(v);
}

export function buildCurlCommand(reqState, opts = {}) {
  const reveal = !!opts.reveal;
  const params = (reqState.params || []).filter(p => p.enabled !== false && p.key);
  let headers = (reqState.headers || []).filter(h => h.enabled !== false && h.key);

  const lines = [];
  let leadingComment = null;

  const authType = reqState.authType || 'none';
  const authConfig = reqState.authConfig || {};
  let basicAuthFlag = null;

  if (authType === 'bearer') {
    headers = [...headers, { key: 'Authorization', value: `Bearer ${authConfig.token || '{{ACCESS_TOKEN}}'}`, enabled: true }];
  } else if (authType === 'basic') {
    const user = authConfig.username || '{{USERNAME}}';
    const pass = authConfig.password || '{{PASSWORD}}';
    basicAuthFlag = _shQuote(`${user}:${pass}`);
  } else if (authType === 'api_key') {
    const keyName = authConfig.key_name || authConfig.key || 'X-API-Key';
    const keyValue = authConfig.key_value || authConfig.value || '{{API_KEY}}';
    if (authConfig.in === 'query') {
      params.push({ key: keyName, value: keyValue, enabled: true });
    } else {
      headers = [...headers, { key: keyName, value: keyValue, enabled: true }];
    }
  } else if (authType === 'oauth2') {
    leadingComment = '# OAuth2 (client credentials) — token fetched at send time, not included below';
  }

  headers = _redactHeaders(headers, reveal);

  let url = reqState.url || '';
  if (params.length) {
    const qs = params.map(p => `${p.key}=${_encodeQueryValue(p.value ?? '')}`).join('&');
    url += (url.includes('?') ? '&' : '?') + qs;
  }

  lines.push(`curl -X ${reqState.method || 'GET'} ${_shQuote(url)}`);
  headers.forEach(h => lines.push(`-H ${_shQuote(`${h.key}: ${h.value}`)}`));
  if (basicAuthFlag) lines.push(`-u ${basicAuthFlag}`);

  const bodyType = reqState.bodyType || 'none';
  if (bodyType === 'raw' || bodyType === 'graphql') {
    if (reqState.body) lines.push(`--data-raw ${_shQuote(reqState.body)}`);
  } else if (bodyType === 'form') {
    (reqState.formRows || []).filter(r => r.enabled !== false && r.key).forEach(r =>
      lines.push(`--data-urlencode ${_shQuote(`${r.key}=${r.value ?? ''}`)}`));
  } else if (bodyType === 'multipart') {
    (reqState.formRows || []).filter(r => r.enabled !== false && r.key).forEach(r => {
      if (r.is_file) {
        // No local filesystem path to reference — emit a placeholder the
        // user swaps for a real path, matching the originally captured name/type.
        const typePart = r.content_type ? `;type=${r.content_type}` : '';
        lines.push(`-F ${_shQuote(`${r.key}=@/path/to/${r.filename || 'file'}${typePart}`)}`);
      } else {
        lines.push(`-F ${_shQuote(`${r.key}=${r.value ?? ''}`)}`);
      }
    });
  }

  const curlCommand = lines.join(' \\\n  ');
  return leadingComment ? `${leadingComment}\n${curlCommand}` : curlCommand;
}
