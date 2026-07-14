# API request assertions — reference

Assertions are no-code pass/fail checks attached to an `api_requests` row (the
`assertions` column, a JSON array). They run after the response comes back,
alongside any script assertions from `qc.expect`/`qc.test` (see
[api-script-reference.md](api-script-reference.md#script-assertions-qcexpect--qctest)
— both land in the same `assertion_results` array).

Frontend: [assertion-builder.js](../web/static/api/components/assertion-builder.js)
(UI for the Assertions tab in the request editor). Backend evaluation:
`_evaluate_assertions`/`_compare`/`_values_equal`/`_contains` in
[cli/api_runner.py](../cli/api_runner.py) (around line 315).

## Assertion shape

```json
{ "type": "json_path", "path": "$.data.id", "op": "eq", "value": 42 }
```

| Field | Meaning |
|---|---|
| `type` | `status` \| `json_path` \| `header` \| `response_time` \| `body_text` |
| `op` | comparison operator, see matrix below |
| `path` | JSONPath expression — `json_path` only |
| `key` | header name — `header` only |
| `value` | expected value (a string typed in the UI — see "Why `value` stays a string" below) — omitted for `exists`/`not_exists` |
| `matchMode` | `first` (default, omitted) \| `any` \| `all` — `json_path` only, see below |

### Why `value` stays a string

The UI used to run `isNaN(value) ? value : Number(value)` on the typed
expected value, which silently mangled two cases: a zero-padded string like a
zip code (`"00501"` → `Number()` → `501`) and very large numeric IDs that lose
precision through JS `Number()` coercion. The builder no longer coerces —
`getAssertions()` in assertion-builder.js sends the exact text typed. The
backend does its own numeric casting where an op actually needs it
(`int()`/`float()` both accept numeral strings directly), and `eq`/`ne` are
type-aware regardless of whether `value` arrives as a string or a real JSON
type (see the operator semantics table below).

## Type × operator matrix

The UI restricts which operators are offered per type. The backend does
**not** enforce this restriction — `_compare` is generic and will evaluate
any `(type, op)` combination sent to it, so a hand-edited/imported assertion
JSON can use an operator the UI never offers for that type.

| Type | Operators (UI) | What's checked |
|---|---|---|
| `status` | `eq` `ne` `lt` `gt` | HTTP status code, compared numerically |
| `json_path` | `eq` `ne` `lt` `gt` `contains` `exists` `not_exists` `matches` | value(s) at a JSONPath expression in the JSON response body |
| `header` | `eq` `ne` `contains` `exists` `not_exists` `matches` | response header value, case-insensitive name lookup |
| `response_time` | `lt` `gt` `eq` | request duration in ms |
| `body_text` | `contains` `eq` `matches` | raw response body as text |

Operator semantics (`cli/api_runner.py:315` onward):

| Op | Semantics |
|---|---|
| `eq` | `_values_equal(actual, expected)` — type-aware, see below |
| `ne` | `not _values_equal(actual, expected)` |
| `lt` / `gt` | `float(actual) < / > float(expected)` — raises (assertion fails with an error) if either side isn't numeric |
| `contains` | `_contains(actual, expected)` — real membership when `actual` is a list/dict (`json_path` match), substring match on `str(actual)` otherwise |
| `exists` | for `json_path`: the path resolved to at least one node (even a JSON `null`); for everything else: `actual is not None` |
| `not_exists` | inverse of `exists` |
| `matches` | `re.search(str(expected), str(actual))` — real regex, case-sensitive, search (not fullmatch), no flags |

### `_values_equal` (type-aware `eq`/`ne`)

`actual` is a real JSON-decoded Python value (`str`/`int`/`float`/`bool`/
`None`/`list`/`dict`); `expected` is normally a plain string from the UI, but
a hand-edited assertion can hand it any JSON type directly.

| `actual` type | Behavior |
|---|---|
| `bool` | compared to a real bool directly, or to a string case-insensitively (`"true"`/`"True"` both match `True`) |
| `None` | matches `None`, or the string `"null"` (case-insensitive) |
| `int`/`float` | matches another number via `float()` cast (`3.0 == 3`), or a numeral string via `float()` cast (`"3"` matches `3.0`) |
| anything else (`str`, `list`, `dict`) | falls back to `str(actual) == str(expected)` |

### `_contains` (real membership for `json_path`)

| `actual` type | Behavior |
|---|---|
| `list`/`tuple` | `any(_values_equal(item, expected) for item in actual)` — e.g. `12` (int) matches an expected `"12"` string via the same type-aware equality, not a raw substring scan of `str([12, 3])` |
| `dict` | matches against either the keys or the values, same type-aware equality |
| everything else (`header`, `body_text`, scalar `json_path`) | `str(expected) in str(actual)` — substring match |

Per-combo status:

| Type | Op | Status |
|---|---|---|
| `status`, `response_time` | `eq`/`ne`/`lt`/`gt` | OK — numeric both sides |
| `body_text` | `contains`/`eq`/`matches` | OK — compares against the full untruncated body (only the *displayed* `actual` is truncated to 200 chars) |
| `header` | `eq`/`ne`/`exists`/`not_exists`/`contains`/`matches` | OK — a missing header only lets `not_exists` pass; other ops fail immediately instead of stringifying `None` into `"None"` |
| `json_path` | all ops | OK — see `matchMode` below for how multi-match paths (wildcard/recursive-descent) are handled |

## JSONPath support (`json_path` type)

Paths are evaluated with [`jsonpath_ng`](https://github.com/h2non/jsonpath-ng)
(`jsonpath-ng>=1.6.0` in `requirements.txt`), using the **base** parser
(`jsonpath_ng.parse`, not `jsonpath_ng.ext`):

```
$.data.id              dot access
$.items[0].name         array index
$.items[*].id           wildcard — all matching nodes
$..id                   recursive descent — every "id" key at any depth
$.items[0:2]            slice
```

**Filter expressions are NOT supported** — `$.items[?(@.active)]` raises a
parse error (that's `jsonpath_ng.ext` syntax, which isn't imported here).
There's no way to assert "the item where x == y" directly; you have to know
the index or use `$..` recursive descent. The path input in the UI carries a
placeholder/help hint calling this out so a `[?(@.x==y)]` path isn't a silent
dead end.

### `matchMode`: handling multiple matches

A wildcard (`$.items[*].id`) or recursive-descent (`$..id`) path can resolve
to more than one node. `matchMode` (UI dropdown next to the operator, only
shown for `json_path`) controls which of the matches must satisfy the op:

| `matchMode` | Behavior |
|---|---|
| `first` (default) | only `matches[0]` is checked — old behavior, still the default so existing saved assertions keep working unchanged |
| `any` | passes if **any** matched node satisfies the op |
| `all` | passes if **every** matched node satisfies the op (and fails if there were zero matches) |

`matchMode` is omitted from the saved JSON when it's `"first"`, so assertions
saved before this feature existed still round-trip identically.

`exists`/`not_exists` ignore `matchMode` — they already mean "the path
resolved to at least one node," which is inherently an "any" check regardless
of value, including a matched JSON `null` (see the worked example below).

## Examples

```json
// Status is 2xx-family exact code
{ "type": "status", "op": "eq", "value": 200 }

// Response under 500ms
{ "type": "response_time", "op": "lt", "value": 500 }

// Content-Type header contains "application/json"
{ "type": "header", "key": "Content-Type", "op": "contains", "value": "application/json" }

// Content-Type header matches a pattern (new: `matches` now available on `header`)
{ "type": "header", "key": "Content-Type", "op": "matches", "value": "application/json;?.*" }

// Nested field equals a value — type-aware now: this passes whether the body
// has "role": "admin" (string) — the only realistic shape for this field —
// and would likewise still pass if the field were numeric/boolean/null and
// the expected text matched by type (see the true/null examples below).
{ "type": "json_path", "path": "$.data.user.role", "op": "eq", "value": "admin" }

// JSON boolean field: body has "active": true (real JSON bool, decoded to
// Python True). Typing the literal word "true" now correctly passes —
// previously str(True) = "True" != "true" always failed.
{ "type": "json_path", "path": "$.data.active", "op": "eq", "value": "true" }

// JSON null field: body has "deletedAt": null. Typing "null" now correctly
// passes — previously str(None) = "None" != "null" always failed.
{ "type": "json_path", "path": "$.data.deletedAt", "op": "eq", "value": "null" }

// Float/int mismatch: body has "total": 3.0 (Python float from json.loads),
// expected typed as "3". Now passes via numeric cast (float(3.0) == float("3"));
// previously "3.0" != "3" as strings always failed.
{ "type": "json_path", "path": "$.data.total", "op": "eq", "value": "3" }

// Zero-padded string preserved exactly: body has "zip": "00501". The UI no
// longer Number()-coerces the typed value, so "00501" stays "00501" instead
// of silently becoming 501 before it's even sent.
{ "type": "json_path", "path": "$.data.zip", "op": "eq", "value": "00501" }

// Real membership in an array match: body has "ids": [12, 3]. Checking for
// "12" now does real element membership (any(_values_equal(item, "12"))),
// so it correctly passes without also spuriously matching on "1" (which used
// to pass because "1" is a substring of str([12, 3]) == "[12, 3]").
{ "type": "json_path", "path": "$.data.ids", "op": "contains", "value": "12" }

// A field exists (any non-null value)
{ "type": "json_path", "path": "$.data.token", "op": "exists" }

// Present-but-null now correctly counts as existing: body has
// "error": null. exists now checks "did the path resolve to a node" (yes —
// jsonpath_ng found a null-valued node), not "is the value truthy" — so this
// passes. Previously it failed because a None value looked identical to "no
// match at all."
{ "type": "json_path", "path": "$.error", "op": "exists" }

// No "error" key anywhere in the response (recursive descent — every "error"
// key at any depth must be absent for not_exists to pass)
{ "type": "json_path", "path": "$..error", "op": "not_exists" }

// not_exists on a response that isn't JSON at all (e.g. a 204 with an empty
// body, or a plain-text error page): the path trivially can't resolve to
// anything, so not_exists now correctly passes instead of being hard-failed.
{ "type": "json_path", "path": "$.data.error", "op": "not_exists" }

// "Any match" mode: at least one item's status must be "active" — checks
// every node $.items[*].status resolves to, passes if any one is "active".
{ "type": "json_path", "path": "$.items[*].status", "op": "eq", "value": "active", "matchMode": "any" }

// "All matches" mode: every item's price must be a positive number — checks
// every node $.items[*].price resolves to, fails if even one doesn't satisfy gt.
{ "type": "json_path", "path": "$.items[*].price", "op": "gt", "value": "0", "matchMode": "all" }

// Response body matches a UUID pattern
{ "type": "body_text", "op": "matches", "value": "[0-9a-f]{8}-[0-9a-f]{4}-.*" }
```

## Fixed in this pass

- **Operator dropdown couldn't be changed away from its initial value**
  ([assertion-builder.js](../web/static/api/components/assertion-builder.js)).
  `typeSelect.onchange`/`opSelect.onchange` both pointed at the same
  `_updateUI`, which unconditionally rebuilt the op `<select>`'s option list
  on every call, including when the op select itself was what just changed —
  rebuilding `innerHTML` mid-`change`-event resets a native `<select>`'s
  `selectedIndex` to `0`. Fix: split into `_rebuildOps()` (option-list
  rebuild, runs only on a type change, preserves the currently-selected op
  across the rebuild if still valid) and `_syncVisibility()` (field show/hide,
  runs on both type and op changes, never touches the option list).
- **Silent eval errors weren't shown in the single-request response panel.**
  [response-panel.js](../web/static/api/components/response-panel.js) only
  surfaced `ar.error` when `ar.type === 'script'`; a no-code assertion that
  hit a backend exception (bad JSONPath, non-numeric `status`/`response_time`
  value) just rendered a plain ✗ with no reason.
  [collection-run-view.js](../web/static/api/views/collection-run-view.js)
  already showed `a.error` for every type — response-panel.js now matches it.
- **Blank expected-value silently became `0`.** `getAssertions()` used to run
  `isNaN(value) ? value : Number(value)`, and `Number('') === 0`, so leaving
  the value field blank on e.g. an `eq` status check silently saved
  `value: 0`. The value input now gets an `assertion-value--invalid` red-
  border state live as you type/change type/change op, `getAssertions()`
  drops any row that's still blank and flags `hasInvalidAssertions()`, and
  [request-editor-view.js](../web/static/api/views/request-editor-view.js)'s
  `_save()` blocks the save with an alert instead of silently persisting a
  wrong `value: 0`.
- **`eq`/`ne` were always string comparisons.** Replaced with type-aware
  `_values_equal` (see table above) — numeric, boolean, and null mismatches
  that used to silently fail (`3.0` vs `3`, `true` vs `True`, `null` vs
  `None`) now compare correctly. The UI also stopped `Number()`-coercing the
  typed value client-side, which separately fixes zero-padded strings
  (`"00501"`) and large-ID precision loss.
- **`json_path` `contains` did substring matching against `str()`/`repr()`**
  of the matched value, not real element/key membership (`"1" in "[12, 3]"`
  spuriously passed). Replaced with `_contains`, which does real list/dict
  membership via `_values_equal` per element, falling back to substring
  matching only for scalar `actual` (where substring *is* the right
  semantic — `header`, `body_text`, a plain string `json_path` match).
- **`json_path` only ever inspected the first match.** Added `matchMode`
  (`first`/`any`/`all`) so wildcard/recursive-descent paths can assert
  "any item matches" or "all items match," not just "the first one."
  Defaults to `first` and is omitted from JSON when default, so existing
  saved assertions are unaffected.
- **`exists`/`not_exists` couldn't distinguish "key present with `null`
  value" from "key absent."** Both now key off whether `jsonpath_ng` found
  any matching node at all (`bool(matches)`), not the truthiness of the
  matched value — a present-but-`null` field now correctly satisfies
  `exists`.
- **`json_path` + `not_exists` on a non-JSON/empty response body was
  hard-coded to fail.** It now passes for `not_exists` (there's trivially no
  matching node) and only fails for other ops, instead of unconditionally
  failing every op when the body isn't JSON.
- **`header` didn't short-circuit on a missing header the way `json_path`
  does.** A missing header used to still run `eq`/`ne`/`contains`/`matches`
  against `str(None)` = `"None"`, so an expected value that happened to
  equal/contain the literal text `"None"` could spuriously pass against a
  header that was never sent. Now a missing header only lets `not_exists`
  pass; every other op fails immediately.
- **Array/object `actual` values rendered unreadably** (`String([1,2,3])` →
  `"1,2,3"`, `String({...})` → `"[object Object]"`). Both response-panel.js
  and collection-run-view.js now `JSON.stringify` non-primitive `actual`
  values before display.
- **No `matches` operator for `header`**, despite the backend already
  supporting it generically. Added to the UI's `TYPE_OPS.header` list —
  useful for patterns like a `Content-Type` check
  (`application/json;?.*`) rather than only exact/contains.
- **No filter-expression support in JSONPath** — documented limitation, not
  a bug: `jsonpath_ng.ext` (which adds `[?(@.x==y)]`) isn't imported, only
  the base parser is. There's no plan to add it in this pass; noted above
  in the JSONPath section so it isn't a silent dead end.

## Maintenance rule

Any change to assertion behavior — `TYPE_OPS`/`OP_LABELS`/`MATCH_MODE_LABELS`/
row wiring in `web/static/api/components/assertion-builder.js`,
`_compare`/`_values_equal`/`_contains`/`_evaluate_assertions` in
`cli/api_runner.py`, the `assertions` column handling in
`web/api/repositories/request_repo.py`, or assertion-result rendering in
`web/static/api/components/response-panel.js` and
`web/static/api/views/collection-run-view.js` — must be reflected in this
document in the same change. Grep for `assertion\|TYPE_OPS\|_compare` if
unsure whether a touched file is in scope.
