## ADDED Requirements

### Requirement: Suite run API item uses the API-run result format
In the suite run-results view and the Execution History modal, an API-request item SHALL be rendered using the same result format the API section's collection-run view uses: a columnar row exposing the request's method, name, status, status code, duration, and assertions count, with a schema-drift pill on the name when drift is present, that expands in place to a detail panel. The detail panel SHALL show, in order, any error/failure reason, the assertion results, the schema-drift comparison (breaking and added entries with each field's type, via the shared schema-drift renderer), and the response body. Suite API items SHALL NOT be drawn with a divergent, cramped row that omits this detail or misaligns its columns across items.

#### Scenario: API item renders in the API-run columnar format
- **WHEN** a suite run's API item is shown in the run-results view or Execution History modal
- **THEN** it displays method, name, status, status code, duration, and an assertions count in aligned columns, matching the layout of the API section's collection-run view, and the columns line up across multiple API items

#### Scenario: Expanded API item shows schema-drift with field types
- **WHEN** a user expands a suite API item whose response produced a schema-drift verdict
- **THEN** the detail panel shows the breaking and added differences with each field's type (e.g. `applicant_ct` / `number`, `auto_invite_candidates` / `int → boolean`), rendered by the same schema-drift renderer the API-run modal uses, followed by the response body

#### Scenario: Expanded API item shows assertions and failure reason
- **WHEN** a user expands a suite API item
- **THEN** the detail panel shows its assertion results (or an explanatory "No assertions — HTTP <code>" line) and, on failure, the error/reason, and shows no negative-testing section

## MODIFIED Requirements

### Requirement: API item auth and schema-check parity with collection runs
When a suite run executes an API-request item, the system SHALL resolve the request's auth configuration and schema-check enablement using the same collection-inheritance rules applied when running the request from its collection directly. The suite run SHALL load and deserialize the API request identically to a collection run, so that the schema-drift baseline is the request's frozen response-schema type-tree (never a raw serialized string) and the drift comparison yields the same verdict as running that request from its collection.

#### Scenario: Auth inherited from collection applies inside a suite run
- **WHEN** an API request has `auth_type` set to inherit-from-collection, and the parent collection defines a bearer auth config
- **THEN** running that request as a suite item sends the request with the collection's bearer auth applied, identical to running it standalone from the collection

#### Scenario: Schema-check runs for a suite API item when enabled
- **WHEN** an API request has schema-check enabled (directly or via collection default) and has a captured baseline schema
- **THEN** a suite run of that item performs the schema-drift comparison and records a verdict, the same as a standalone collection run would

#### Scenario: Suite schema-drift verdict matches the collection run for the same request
- **WHEN** a request whose live response still matches its frozen response-schema baseline is run both as a suite item and from its collection
- **THEN** both runs record the same schema-drift verdict, and the suite run does NOT report a breaking drift caused by comparing an unparsed baseline against the inferred type-tree

### Requirement: Suite API item variable persistence
When a suite run's API item extracts or sets a variable (via `qc.set`, pre/post extractor, or pre/post script), the system SHALL persist that value into the request's parent collection's variable store, the same way a collection run persists it, and SHALL also make that value available to later items in the same suite run regardless of their type. A later item's read SHALL NOT be lost because an intervening web-script item snapshots browser state.

#### Scenario: Extracted variable is visible after the suite run completes
- **WHEN** a suite API item's post-script calls `qc.set("access_token", value)`
- **THEN** after the suite run finishes, that value is readable as the collection's `access_token` variable the same way it would be after a collection run

#### Scenario: Script item reads a variable extracted by an earlier API item
- **WHEN** a suite runs an API item that extracts a token, followed by a web script item
- **THEN** the script item can read that token via its `QACLAN_STATE_<KEY>` environment variable, regardless of whether another item ran in between

#### Scenario: A later API item reuses a token extracted by an earlier API item
- **WHEN** a suite runs a login API item that extracts `access_token`, followed by another API item whose auth or request references that token
- **THEN** the later API item resolves the token to the value the login extracted and authenticates successfully, the same as when the two run sequentially in a collection

#### Scenario: A web-script snapshot does not drop earlier extracted variables
- **WHEN** an API item extracts a variable and a subsequent web-script item snapshots browser storage state to the shared state file
- **THEN** the snapshot preserves the previously extracted variables, so an item after the script still reads them
