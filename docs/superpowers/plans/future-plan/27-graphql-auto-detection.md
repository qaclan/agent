# 27 - GraphQL Auto-Detection During Discovery

Parked out of scope from [2026-07-18-graphql-body-editor.md](../2026-07-18-graphql-body-editor.md). Full design worked through in conversation; not built because we're pre-seed and have no evidence yet of how many users' target apps are GraphQL vs REST. Revisit when a specific design partner or prospect hits this wall — not before.

## The problem

`web/api/routes/discovery.py`'s record/HAR-based capture (`record_start`/`record_stop`) never tags a captured request `body_type='graphql'` — only Postman import does (`cli/api_discovery/postman_parser.py:81-84`). So a recorded browser session capturing a real GraphQL API call (e.g. `POST https://rickandmortyapi.graphcdn.app/` with a `{query,variables,operationName}` JSON body) lands as `body_type='raw'`, indistinguishable from any other JSON REST call, unless the user manually notices and flips the tab.

## Why this is hard (ruled out approaches)

- **URL path contains `/graphql`** — not reliable. Real GraphQL CDNs/deployments use arbitrary paths (the rickandmorty example above is `POST /` on `graphcdn.app`, no `graphql` in the path at all).
- **Client library headers** (Apollo `apollographql-client-name`, etc.) — vendor-specific, not part of any GraphQL spec, and plenty of real apps talk GraphQL via plain `fetch`/Relay/urql with zero distinguishing headers. Ruled out entirely — never score on vendor headers.
- **Presence of a `query` key in the body** — false-positives against REST search/filter endpoints, MongoDB/Elasticsearch-style query-DSL bodies, etc. The disambiguator that actually works: GraphQL's `query` value is always a **string**; DB/search-DSL "query" fields are almost always a nested **object**. Requiring `query` to be a string already kills most collision risk.
- **Even Postman doesn't auto-detect from a pasted curl** — confirmed by testing: pasting the exact rickandmorty curl into Postman still requires the user to manually pick "GraphQL" body mode. This is the actual industry bar, not an oversight to fix.

## Proposed design (for whenever this gets picked up)

### Detection signals — vendor-neutral, spec-based only

**Strong (near-conclusive alone):**
- Request or response `Content-Type` is `application/graphql-response+json` or `application/graphql` — official GraphQL-over-HTTP media types (2023 spec).
- Request body is a JSON **object** (or, per the note below, an **array** of such objects for batched requests) whose top-level keys are a non-empty subset of `{query, operationName, variables, extensions}`, `query` is present and a **string**, and that string parses as GraphQL document grammar (optional `query`/`mutation`/`subscription`/`fragment` keyword, optional name + `($var: Type!)` defs, balanced `{...}` selection set — a real grammar/brace-balance check, not "contains a brace somewhere").
- Response body is a JSON object whose top-level keys are a non-empty subset of `{data, errors, extensions}`, with `errors` (if present) being an array of objects each containing a `message` string.

**Medium (corroborating, stack for confidence):**
- Same exact endpoint URL (scheme+host+path, ignoring query string) reused across multiple captured requests in one recording session with differing `operationName`/body — GraphQL funnels through one endpoint; REST varies path per resource.

### Known coverage gaps (from a from-scratch adversarial pass on the "strong" signal above — track these, don't silently claim full coverage)

- **GET-based GraphQL** — some deployments (notably CDN-cached ones, e.g. exactly the graphcdn.app pattern from the motivating example) support `GET /path?query=...&variables=...`. The body-shape check above only looks at POST JSON bodies; extend it to also parse URL query params the same way.
- **Batched requests** — Apollo's default batch-http-link / urql batch exchange send a JSON **array** of `{query,variables,operationName}` objects in one POST, not a single object. Must accept top-level arrays where every element matches, not just single objects.
- **Multipart file uploads** — the GraphQL multipart request spec (`graphql-upload`, Apollo Upload Client) sends `multipart/form-data` with an `operations` field holding the JSON-encoded query+variables, plus a `map` field and file parts. `Content-Type` isn't `application/json` at all here — entirely invisible to the body-shape check as designed; would need a dedicated multipart-field check.
- **WebSocket subscriptions** (`graphql-ws`/`subscriptions-transport-ws`) — real-time GraphQL runs over WS, not HTTP request/response, and may not even be captured by the current HAR-based recorder depending on what it taps. Would need a separate WS-frame parser (`{"type":"subscribe","payload":{"query":...}}`) — a different code path entirely, not an extension of the HTTP-based scorer.
- **Automatic Persisted Queries (APQ)** — body is just `{"extensions":{"persistedQuery":{"sha256Hash":"..."}}}`, no `query` text at all. Undetectable without a hash registry. Accept as a documented miss.

Passive detection realistically covers the dominant case (single-operation, POST, JSON-object body) well; the above gaps mean it will never be exhaustive. That's expected — see the maker-checker framing below, which treats this as a triage aid, not a ground-truth classifier.

### A stronger complementary mechanism: active introspection probe

Passive traffic sniffing can never reach certainty. The mechanism the GraphQL ecosystem actually uses for certainty (GraphiQL, Insomnia, Postman's "generate from schema") is: fire `POST {url} {"query":"{__schema{types{name}}}"}` at the candidate endpoint and check for a valid `{"data":{"__schema":{"types":[...]}}}` response shape. Success = 100% confirmed GraphQL server, plus you get the full schema for free (enables real field/type-aware autocomplete in the Query editor, not just syntax highlighting — see the "Related / Out of Scope" note in the main plan). Failure/blocked (introspection disabled in production, common hardening) just falls back to the heuristic.

### Recommended flow when this gets built

1. Passive shape-scorer runs offline during HAR parsing (`cli/api_discovery/har_parser.py`), computing `confidence: 0-100` + `evidence: [...]` per captured request. Pure, unit-testable function.
2. **Never** auto-sets `body_type='graphql'` — always lands as `raw` by default (safe, non-destructive).
3. Confidence ≥70 → "likely GraphQL" badge in the discovery review UI (`web/static/api/views/request-review-modal.js`); 40-69 → "possible", visually deprioritized; <40 → not surfaced. This is a **bulk-discovery triage aid** — its value is scanning dozens/hundreds of captured requests from one recording session to spot the few GraphQL calls, not saving a click on a single manually-pasted curl (where the user already knows what they captured).
4. Badge includes a "Verify" button that fires the live introspection probe on demand — user-triggered only, never automatic (respects maker-checker, avoids surprise outbound calls during otherwise-offline discovery review). Success = certainty + bonus schema; failure = falls back to heuristic confidence, user decides manually via the split-pane editor from the main plan.

## Why parked

Pre-seed stage — engineering hours are the scarcest resource, and this is speculative breadth (an unvalidated segment size) rather than depth on the core workflow. Building it now would be optimizing for a "someone might have a GraphQL app someday" story instead of real signal. The trigger to revisit: a specific design partner or prospect explicitly hits this wall and asks, or a deal stalls because of it — not a roadmap date.
