## Purpose

Lets a suite hold an ordered mix of web scripts and API requests, editable and reorderable as one list, with API items executing under the same auth/schema-check rules as a standalone collection run, persisting and sharing variable state correctly regardless of item order, while deliberately excluding negative testing from the suite context.

## ADDED Requirements

### Requirement: Unified suite item list
The suite editor SHALL present script and API-request items in a single ordered list. The system SHALL NOT render a separate, duplicate list of scripts alongside the mixed item list.

#### Scenario: Suite with both item types
- **WHEN** a user opens the edit view for a suite containing 2 scripts and 1 API request
- **THEN** the editor shows one list with 3 rows in suite order, each row labeled with its type (script or API request)

#### Scenario: Removing an item
- **WHEN** a user removes an item from the list, regardless of its type
- **THEN** the item is removed from the suite via a single removal path and no longer appears in the list

#### Scenario: Row actions are right-aligned
- **WHEN** a suite item row renders, for either item type
- **THEN** its View and Remove controls are aligned to the row's right edge regardless of how long the item's name/method/URL text is

#### Scenario: Removing an item requires confirmation
- **WHEN** a user clicks an item row's Remove control
- **THEN** a confirm dialog appears before anything is deleted, and the item is only removed from the suite if the user confirms

#### Scenario: Viewing an API item opens its request editor
- **WHEN** a user clicks View on an API-request row in the suite editor
- **THEN** the suite editor closes and the API section opens directly in that request's own editor (same editor used from a collection), with the request selected in its collection's sidebar tree

### Requirement: Mixed-item reordering
The suite editor SHALL allow drag-and-drop reordering across script and API-request items in the same list, and the persisted order SHALL reflect the resulting sequence for every item regardless of type.

#### Scenario: Reordering scripts does not scramble API item position
- **WHEN** a suite contains [Script A, API B, Script C] and a user drags Script C above API B
- **THEN** the persisted order becomes [Script A, Script C, API B] and a subsequent suite run executes items in that exact sequence

#### Scenario: Reordering an API item relative to scripts
- **WHEN** a user drags an API-request item to a new position among script items
- **THEN** the new position is persisted and reflected on next load of the suite editor

### Requirement: Bulk API request picker
Adding API requests to a suite SHALL present a fixed-height, independently scrolling list of available API requests grouped by their parent collection, each with a checkbox, and a search/filter control. The picker SHALL allow selecting requests from more than one collection in a single add operation. Each collection group SHALL be collapsible and SHALL show a live count of how many of its requests are currently checked.

#### Scenario: Selecting requests from multiple collections
- **WHEN** a user opens the API request picker and checks 2 requests from Collection A and 1 request from Collection B
- **THEN** confirming the selection adds all 3 requests to the suite as separate items, appended in the order selected

#### Scenario: Filtering the picker
- **WHEN** a user types a search term into the picker's filter box
- **THEN** only API requests whose name, method, or URL match the term remain visible, grouped by their collection, and the picker's own height does not change — the list area scrolls internally rather than the modal shrinking or growing with the result count

#### Scenario: Collapsing a collection group
- **WHEN** a user clicks a collection group's header
- **THEN** that group's request rows collapse (or expand if already collapsed); this is a session-only UI toggle, not persisted anywhere

#### Scenario: Live selected-count per group
- **WHEN** a user checks or unchecks requests belonging to a collection group
- **THEN** that group's header shows the current count of checked requests within it, computed from the picker's in-memory selection at render time — no selection count is persisted or remembered across picker sessions

#### Scenario: Searching auto-expands matching groups
- **WHEN** a search term is active and a collapsed group has a matching request
- **THEN** that group renders expanded so the match is visible, regardless of its collapsed/expanded toggle state

### Requirement: API item auth and schema-check parity with collection runs
When a suite run executes an API-request item, the system SHALL resolve the request's auth configuration and schema-check enablement using the same collection-inheritance rules applied when running the request from its collection directly.

#### Scenario: Auth inherited from collection applies inside a suite run
- **WHEN** an API request has `auth_type` set to inherit-from-collection, and the parent collection defines a bearer auth config
- **THEN** running that request as a suite item sends the request with the collection's bearer auth applied, identical to running it standalone from the collection

#### Scenario: Schema-check runs for a suite API item when enabled
- **WHEN** an API request has schema-check enabled (directly or via collection default) and has a captured baseline schema
- **THEN** a suite run of that item performs the schema-drift comparison and records a verdict, the same as a standalone collection run would

### Requirement: Negative testing excluded from suite runs
A suite run SHALL NOT resolve or execute negative test cases for any API item, regardless of the `negative_check` configuration on the request or its collection.

#### Scenario: Negative-check enabled request run inside a suite
- **WHEN** an API request has `negative_check` enabled at the request or collection level, and is run as a suite item
- **THEN** the suite run sends only the base request (no mutated negative cases) and the result contains no negative-testing verdict

### Requirement: Suite API item failure conditions
The system SHALL treat a suite API item as failed when any of the following occur: an assertion fails, the request errors before receiving a response, or the schema-drift comparison returns a breaking verdict. A suite configured to stop on failure SHALL halt on any of these conditions the same way it halts on a failed script item.

#### Scenario: Breaking schema drift halts a stop-on-fail suite
- **WHEN** a suite is configured to stop on failure and an API item's response produces a breaking schema-drift verdict
- **THEN** the suite run marks that item failed and skips the remaining items

#### Scenario: Non-breaking schema drift does not fail the item
- **WHEN** an API item's response produces an additive (non-breaking) schema-drift verdict and all assertions pass
- **THEN** the item is recorded as passed

### Requirement: Suite API item variable persistence
When a suite run's API item extracts or sets a variable (via `qc.set`, pre/post extractor, or pre/post script), the system SHALL persist that value into the request's parent collection's variable store, the same way a collection run persists it, and SHALL also make that value available to later items in the same suite run regardless of their type.

#### Scenario: Extracted variable is visible after the suite run completes
- **WHEN** a suite API item's post-script calls `qc.set("access_token", value)`
- **THEN** after the suite run finishes, that value is readable as the collection's `access_token` variable the same way it would be after a collection run

#### Scenario: Script item reads a variable extracted by an earlier API item
- **WHEN** a suite runs an API item that extracts a token, followed by a web script item
- **THEN** the script item can read that token via its `QACLAN_STATE_<KEY>` environment variable, regardless of whether another item ran in between

### Requirement: Suite run history and downloaded report include API items
Reopening a past suite run's results, and downloading that run's HTML report, SHALL include every API item's outcome alongside script items, in the same execution order, not just the totals. The system SHALL NOT display a total item count that is inconsistent with the number of item rows shown.

#### Scenario: Reopening a past run from the Runs list
- **WHEN** a user reopens the execution history for a suite run that included API items
- **THEN** every API item appears as a row alongside the script items, in original suite order, with its status, status code, duration, and assertion results

#### Scenario: Downloading the HTML report for a run with API items
- **WHEN** a user downloads the report for a suite run that included API items
- **THEN** the downloaded HTML includes a card for each API item, in original suite order, alongside the script cards, with status, status code, duration, assertion results, and schema-drift verdict when present

### Requirement: Suite run results show API item detail in place
The suite run-results view SHALL let a user expand an API item's row to see its status code, response headers, response body, assertion results, and schema-drift verdict (when produced), sourced from that suite run's own persisted result for the item. The expanded view SHALL NOT include a negative-testing verdict, since suite runs never produce one, and SHALL NOT expose the request's editable configuration (auth, pre/post script, params).

#### Scenario: Expanding an API item with a schema-drift result
- **WHEN** a user expands a suite run's API item row for an item that produced a schema-drift verdict
- **THEN** the expanded panel shows the drift verdict alongside status code, response body, headers, and assertion results

#### Scenario: Expanding an API item shows no negative section
- **WHEN** a user expands any suite run's API item row
- **THEN** no negative-testing verdict or section appears, since suite runs never execute negative cases
