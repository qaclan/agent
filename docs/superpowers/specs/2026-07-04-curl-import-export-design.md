# cURL Import/Export Design

## Goal

Add Postman-parity curl copy/paste to the API request editor, plus one safety
feature Postman lacks (secret redaction on copy). Three surfaces:

- **A.** "Copy as cURL" button in the request editor.
- **B.** Paste a curl command directly into the URL box → auto-fills the editor.
- **C.** Dedicated "Import cURL" dialog for bulk/messy multi-command paste.
- **D.** Auto-redact secrets on copy (differentiator vs Postman's plaintext copy).

Out of scope for this round (deferred): multi-format copy (fetch/python/httpie),
universal smart-paste (HAR/Postman-JSON detection in the URL box).

## Existing patterns this builds on

- Import parsers live in `cli/api_discovery/` — one file per format
  (`har_parser.py`, `openapi_parser.py`, `postman_parser.py`, `bruno_parser.py`),
  each exposing `parse_X(...) -> list[dict]` with a common request-dict shape:
  `{name, method, url, params: [{key,value,enabled}], headers: [...], body, body_type}`.
- `web/api/routes/discovery.py` exposes a `/preview` route per format (parses,
  returns the list, no save) and reuses one generic `/discover/save-requests`
  route to persist whatever the client selected.
- `web/static/api/views/request-review-modal.js` is the shared picker UI —
  every importer feeds it the same request-dict list.
- `web/static/api/views/postman-import-view.js` is the template for a new
  single-format import view (file/textarea → preview → review modal).
- `web/static/api/views/discover-modal.js` is the entry-point grid of import
  options ("Record APIs", "Import HAR", "Import Postman", ...).
- `cli/api_discovery/har_parser.py:_SENSITIVE_RE` already regexes for
  password/secret/token/authorization/api-key/auth — reused for redaction.

## A. Copy as cURL (request editor)

**File:** `web/static/api/views/request-editor-view.js`, button added next to
the existing Send button in the URL bar (~line 96-99).

Pure client-side, no backend call — builds the curl string directly from live
in-memory editor state (method select, url input, params table, headers table,
body textarea + body_type), the same state `_save()` already reads.

New helper module `web/static/api/lib/curl-builder.js`:
`buildCurlCommand({method, url, params, headers, body, bodyType}) -> string`.

- URL: append enabled `params` as query string (encode values, but leave
  `{{VAR}}` tokens un-encoded/literal — detect via `{{...}}` regex before
  encoding, re-splice after).
- Headers: one `-H "Key: Value"` per enabled row, `{{VAR}}` kept literal.
- Body by `body_type`:
  - `raw` → `--data-raw '<body>'` (shell-single-quote-escape: replace `'`
    with `'\''`).
  - `form` → one `--data-urlencode 'key=value'` per row.
  - `multipart` → one `-F 'key=value'` per row.
  - `graphql` → `--data-raw '<json-stringified {query, variables}>'`.
  - `none` → omitted.
- Multi-line output with trailing `\` per flag (Postman/Insomnia-style
  readability), single-quote-based escaping throughout (safe for `{{VAR}}`
  since it contains no special shell chars).
- **Redaction (Section D):** before building headers, scan header keys against
  `SENSITIVE_HEADER_RE` (JS port of `har_parser._SENSITIVE_RE`: password,
  secret, token, authorization, api[-_]?key, auth). For matches whose value is
  NOT a `{{VAR}}` token, mask the value (e.g. `Bearer ***REDACTED***`,
  keep first/last 2 chars of cookies as a hint). Button has a small "Copy
  (unmasked)" secondary action gated behind one extra click / a tooltip
  warning, not the default.
- On click: `navigator.clipboard.writeText(curl)`, `window._toast('Copied as cURL')`.

## B. Paste-into-URL-box smart import

**File:** `web/static/api/views/request-editor-view.js`, `paste` listener
added to `urlInput`.

```
urlInput.addEventListener('paste', async (e) => {
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!/^\s*curl(\.exe)?\s/i.test(text)) return; // normal paste, let it through
  e.preventDefault();
  if (/* editor has non-empty headers/body/params already */) {
    const ok = await window._confirmDialog('Replace current request fields with parsed curl?');
    if (!ok) return;
  }
  const res = await window.api('POST', '/discover/curl/preview', { curl: text });
  if (!res.ok) { window._toast('Could not parse curl: ' + res.error); return; }
  const parsed = res.requests[0]; // first command if multiple pasted
  // fill methodSelect, urlInput, paramsTable, headersTable, body/bodyType, re-run _syncPathVars()
});
```

Uses the **backend** parser (not a second JS implementation) so single-request
paste-fill and bulk dialog import (Section C) share one source of truth.

## Backend: curl parser + routes

**New file:** `cli/api_discovery/curl_parser.py`

```python
def parse_curl(text: str) -> list[dict]:
    """Parse one or more curl commands (shell-line-continuation aware) into
    the standard request-dict list: [{name, method, url, params, headers, body, body_type}]."""
```

- Split input into separate curl invocations: each line (after joining `\`
  and `^`-style continuations) that starts a new top-level `curl ` command
  starts a new request.
- Tokenize with `shlex.split(..., posix=True)` per command (handles quotes).
- Recognize: `-X/--request`, `-H/--header` (repeatable), `-d/--data-raw
  /--data/--data-binary/--data-urlencode` (repeatable, joined with `&` for
  urlencode), `-F/--form` (→ `multipart`), `-u/--user user:pass` (→
  base64-encode the literal `user:pass` into `Authorization: Basic <base64>`,
  matching what curl itself sends over the wire — a pasted curl command only
  ever contains literal strings, never `{{VAR}}` tokens, so there is nothing
  to preserve unresolved here), `-b/--cookie` (→ `Cookie` header), `-G`
  (force data onto query string),
  `--compressed`/`-s`/`-v`/`-i`/`-k`/`--http1.1`/`--http2` (ignored, no
  request-shape effect).
- URL: split off `?query` into `params` list like `postman_parser.py` does.
- Method inference: explicit `-X` wins; else `POST` if any data flag present,
  else `GET`.
- Body type inference: `-F` present → `multipart`; `-d`/`--data*` present →
  `raw` (or `form` if `Content-Type: application/x-www-form-urlencoded`
  header explicitly set and data looks like `k=v&k=v`); else `none`.
- Unparseable command → skip with a logged warning, don't crash the whole
  batch (matches `bruno_parser` per-file tolerance).

**New routes** in `web/api/routes/discovery.py` (next to the other
`/preview` routes):

```
POST /api/discover/curl/preview   { curl: "<text>" } -> { ok, requests: [...] }
POST /api/discover/curl           { curl_text, collection_name } -> full import+save,
                                     mirrors discover_postman for consistency
                                     (not required by A/B, added for parity/CLI reuse)
```

## C. Bulk "Import cURL" dialog

**New file:** `web/static/api/views/curl-import-view.js`, modeled directly on
`postman-import-view.js`:

```js
export function showCurlImport() {
  // textarea instead of file input — paste one or many curl commands
  // "Preview Requests" -> POST /api/discover/curl/preview -> showRequestReviewModal(requests, name)
}
```

Wired into `discover-modal.js` options array as a new card (after Postman,
before Bruno): `{ icon: '⌨️', title: 'Import cURL', desc: 'Paste one or more curl commands', action: showCurlImport }`.

Save path unchanged — reuses `/discover/save-requests` and
`request-review-modal.js` as-is.

## Error handling

- Malformed curl (unbalanced quotes, unknown required flag) → per-command
  skip in the parser; `/preview` returns `{ok: true, requests: [...], skipped: N}`
  so partial batches still work; UI toasts "Imported N, skipped M — check
  syntax" when `skipped > 0`.
- Empty paste / non-curl text in URL box → falls through to normal paste,
  no-op from the feature's perspective.
- Clipboard write failure (rare, permissions) → catch and toast
  "Couldn't copy — check clipboard permissions".

## Testing

No automated test suite in this repo (per CLAUDE.md). Manual verification:

- Copy: build a request with vars in URL/headers/body across each
  `body_type`, copy, paste resulting string into a real terminal, confirm it
  runs and matches intent (with `{{VAR}}` swapped to a real value by hand).
- Redaction: request with a literal (non-`{{VAR}}`) `Authorization: Bearer sk-...`
  header → copy → confirm masked; confirm reveal path produces the real value.
- Paste-fill: copy a real curl command (e.g. from Chrome DevTools "Copy as
  cURL") into the URL box on both a blank new request and one with existing
  data (confirm-overwrite prompt path).
- Bulk import: paste 3 concatenated curl commands into the new dialog,
  confirm all 3 appear in the review modal, confirm partial-failure toast
  when one command is deliberately malformed.
