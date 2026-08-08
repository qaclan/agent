# api-negative-testing Specification

## Purpose
Verifies that an API rejects invalid, malformed, and malicious input correctly — the right client-error status, no server crash, and no acceptance of bad data — by auto-generating and running negative test cases from a request the user already has, so testers get unhappy-path coverage without hand-authoring every case.
## Requirements
### Requirement: Opt-in negative testing with collection-default master switch

The system SHALL let a user enable negative testing per request without it being on by default. Enablement SHALL follow an inheritance model: a collection carries a default negative-testing state (on or off), and each request carries an override with three states — inherit, on, off. The effective state for a run SHALL be the request override when it is `on` or `off`, otherwise the collection default. Changing the collection default SHALL act as a master switch: it SHALL reset every request's override in that collection to `inherit`, so all requests follow the new default. A user MAY re-apply a per-request override afterward.

#### Scenario: Default is off for a new request in a collection with default off

- **WHEN** a request has an `inherit` override and its collection default is off
- **THEN** negative testing SHALL NOT run for that request

#### Scenario: Collection default on cascades by inheritance

- **WHEN** a collection default is set to on and a request has an `inherit` override
- **THEN** negative testing SHALL run for that request

#### Scenario: Request override wins over collection default between toggles

- **WHEN** a request override is `off` and its collection default is on, with no collection-default change since the override was set
- **THEN** negative testing SHALL NOT run for that request

#### Scenario: Changing the collection default overwrites all overrides

- **WHEN** a collection default is changed while some requests have explicit `on` or `off` overrides
- **THEN** every request's override in that collection SHALL be reset to `inherit` and all requests SHALL follow the new collection default

### Requirement: Auto-generation of negative cases from a happy-path request

The system SHALL generate negative test cases from a request's resolved body, query params, path params, and auth, covering three categories: input validation (per field — missing required, wrong type, null, empty, boundary, enum violation, format violation; plus body-level malformed JSON, oversized payload, and extra unexpected field), request-level mutators (missing/garbage/expired auth, wrong HTTP method, wrong or missing content type, unknown route), and injection/security fuzz (a curated payload set per string field). Generation SHALL work from the request alone; when per-field constraints from an imported API specification are available, the system SHALL use them to produce exact boundary and enum-violation cases. Every generated case SHALL be an editable object a user can enable, disable, or modify — never an opaque black box.

#### Scenario: Cases generated across all three categories from a request with a JSON body

- **WHEN** a user generates negative cases for a request that has a JSON body with fields, a query param, and bearer auth
- **THEN** the system SHALL produce input-validation cases per field, request-level cases (including a missing-auth case), and injection cases for string fields

#### Scenario: Spec constraints sharpen generation

- **WHEN** a request carries per-field constraints from an imported specification (for example a numeric field with a minimum and maximum, and a field with an enum)
- **THEN** the generated cases SHALL include exact boundary values around the min/max and a value outside the enum

#### Scenario: Generation works without a specification

- **WHEN** a request has no imported constraints and a user generates cases
- **THEN** the system SHALL still infer field types from the request and generate cases, without requiring a specification

#### Scenario: Generated cases are editable

- **WHEN** a user edits a generated case's expected status or disables it
- **THEN** the change SHALL persist with the request and be respected on the next run

### Requirement: Expected-rejection contract per case

Each negative case SHALL carry an expected-rejection contract that the system evaluates against the actual response. The contract SHALL default to a category-appropriate expected client-error status (for example missing auth expects 401, wrong content type expects 415, invalid input expects 400 or 422, wrong method expects 405) and MAY be overridden per case. Injection cases SHALL additionally assert that the response is not a server error and that the payload is not reflected verbatim in the response.

#### Scenario: Default expected status applies by category

- **WHEN** a missing-auth case is generated
- **THEN** its default expected status SHALL be 401

#### Scenario: Per-case expected status override is honored

- **WHEN** a user sets a case's expected status to 404 because the API returns 404 instead of 403
- **THEN** the run SHALL evaluate that case against 404

#### Scenario: Injection case asserts no server error and no reflection

- **WHEN** an injection case runs and the API returns a server error, or reflects the payload verbatim in the body
- **THEN** the case SHALL be reported as failed

### Requirement: Negative case execution

When negative testing is active for a request, the system SHALL run each enabled case as a send derived from the request with that case's mutation applied, evaluate the response against the case's expected-rejection contract, and record a per-case pass/fail outcome. Executing negative cases SHALL NOT require the user to author or duplicate additional requests.

#### Scenario: Each enabled case produces one outcome

- **WHEN** a request with three enabled negative cases is run with negative testing active
- **THEN** the system SHALL send three derived requests and record a pass/fail outcome for each

#### Scenario: Disabled cases are skipped

- **WHEN** a case is disabled
- **THEN** the system SHALL NOT send it and SHALL NOT count it in the outcome

### Requirement: Severity classification with false-pass as the primary signal

The system SHALL classify each negative-case outcome by severity using a fixed mapping. A case where the API accepted invalid input (returned a success status where a client error was expected) SHALL be classified Critical and identified as a false pass. Injection reflected or executed, and a server error on a fuzzed input, SHALL also be Critical. A server-error crash on an ordinary validation case, or a wholly wrong status family, SHALL be Major. A rejection with the wrong specific client-error code, an inconsistent error schema, or a missing rate-limit/allow header SHALL be Minor. The false-pass outcome SHALL be surfaced prominently rather than presented as an ordinary failure.

#### Scenario: Accepted invalid input is a Critical false pass

- **WHEN** a case expecting a client-error status receives a 2xx success response
- **THEN** the outcome SHALL be classified Critical and flagged as a false pass

#### Scenario: Wrong specific code is Minor

- **WHEN** a case expecting 422 receives 400 (still a client-error rejection)
- **THEN** the outcome SHALL be classified Minor

#### Scenario: Server error on a fuzzed input is Critical

- **WHEN** an injection case receives a 5xx server-error response
- **THEN** the outcome SHALL be classified Critical

### Requirement: Severity-based run verdict

The system SHALL fail a request run when its negative testing reports at least one Critical or Major outcome. The system SHALL keep a request run passing when negative testing reports only Minor outcomes or all cases pass. A negative-testing failure SHALL be distinguishable in results from an ordinary assertion failure. When negative testing is skipped (not enabled, or no cases exist), it SHALL NOT change the run verdict.

#### Scenario: A Critical outcome fails the run

- **WHEN** negative testing reports one or more Critical outcomes
- **THEN** the request run status SHALL be failed and the result SHALL indicate a negative-testing failure

#### Scenario: Only Minor outcomes keep the run passing

- **WHEN** negative testing reports only Minor outcomes
- **THEN** the request run SHALL remain passing and the Minor outcomes SHALL still be reported

#### Scenario: Skipped negative testing does not affect verdict

- **WHEN** negative testing is not enabled for a request
- **THEN** the run verdict SHALL be determined solely by assertions and status code, as if negative testing were absent

### Requirement: Negative-case authoring surface

The system SHALL provide an authoring surface for negative cases on a request, presenting targets (fields and request-level mutations) against mutation types. From this surface a user SHALL be able to generate cases, enable or disable an individual case, bulk-enable or bulk-disable a whole mutation type, and edit a case's expected status, then run the negative cases. In the field-by-mutation matrix, each mutation-type column header SHALL present a checkbox control that bulk-toggles that whole column and reflects the column's aggregate state: selected when every case in the column is enabled, cleared when every case is disabled, and indeterminate when the column is mixed. The target (field) column SHALL NOT present such a control. Each mutation-type column header SHALL carry a descriptive tooltip stating what that mutation sends and how its outcome is judged. The authoring surface SHALL be configuration-only: it decides which cases run and their contract, and running presents per-case outcomes in the result surface rather than inline in the authoring grid.

#### Scenario: Generate populates the authoring surface

- **WHEN** a user opens the negative view for a request and generates cases
- **THEN** the surface SHALL show a control per applicable target-and-mutation combination, each carrying its default expected-rejection contract

#### Scenario: Bulk-toggle a mutation type

- **WHEN** a user activates a mutation-type column's header checkbox
- **THEN** every case in that column SHALL flip to the same enabled state in a single action

#### Scenario: Column header reflects the column's aggregate state

- **WHEN** the cases in a mutation-type column are all enabled, all disabled, or a mix of both
- **THEN** that column's header checkbox SHALL be shown selected, cleared, or indeterminate respectively

#### Scenario: The target column carries no bulk control

- **WHEN** the field-by-mutation authoring matrix is shown
- **THEN** only mutation-type column headers SHALL present a bulk-toggle checkbox, and the field (target) column header SHALL NOT

#### Scenario: Column header describes its mutation

- **WHEN** a user hovers a mutation-type column header
- **THEN** a tooltip SHALL describe what that mutation sends and how a pass is judged

#### Scenario: Outcomes appear in the result surface after a run

- **WHEN** a user runs the negative cases from the authoring surface
- **THEN** the per-case pass/fail outcome and severity SHALL be presented in the result surface (not inline in the authoring grid)

#### Scenario: Empty state guides first generation

- **WHEN** a user opens the negative view for a request that has no cases yet
- **THEN** the view SHALL present an action to generate cases rather than a blank grid

#### Scenario: Outcomes are distinguishable without relying on color

- **WHEN** a case outcome is presented in the authoring surface or the result surface
- **THEN** its state (passed, failed, disabled, or not yet run) SHALL be conveyed by a word label or the actual status code in addition to color, not by color alone

### Requirement: Category- and severity-grouped reporting with history persistence

The system SHALL report negative-testing outcomes grouped by category, showing every case's outcome compactly, with failures surfaced and false passes highlighted by a headline verdict. Negative outcomes SHALL fold into collection runs so each request result carries a negative-testing indicator summarizing passed-of-total and worst severity. Negative verdicts SHALL be persisted with run history so a past run's negative outcomes can be reviewed after the fact, and SHALL be included in the downloadable run report.

#### Scenario: Run detail groups outcomes by category and highlights failures

- **WHEN** a user opens the negative-testing detail for a completed request
- **THEN** the detail SHALL group outcomes by category, show each case's outcome, and highlight any false pass

#### Scenario: False pass is surfaced ahead of other outcomes

- **WHEN** a completed request has at least one false pass among its negative outcomes
- **THEN** a headline verdict SHALL name the false pass ahead of the category-grouped detail so it is seen first

#### Scenario: Collection run marks requests with negative outcomes

- **WHEN** a collection run includes a request whose negative testing reported failures
- **THEN** that request's row SHALL display a negative-testing indicator reflecting passed-of-total and the worst severity

#### Scenario: Past run retains its negative verdict

- **WHEN** a user reviews a completed run in history or the downloadable report
- **THEN** the stored negative-testing verdict for each request SHALL be available for review

### Requirement: Headless run with severity-gated exit code

The system SHALL provide a headless (command-line) way to run negative testing and SHALL return a non-zero exit code when any Critical or Major outcome is present, and a zero exit code otherwise, so continuous-integration pipelines can gate on negative-testing results.

#### Scenario: Critical outcome gates CI

- **WHEN** a headless negative run produces a Critical false pass
- **THEN** the command SHALL exit non-zero

#### Scenario: Clean or Minor-only run passes CI

- **WHEN** a headless negative run produces only passing or Minor outcomes
- **THEN** the command SHALL exit zero

### Requirement: Safety gate for destructive negative runs

Because negative cases can fire state-changing HTTP methods (POST, PUT, PATCH, DELETE) carrying invalid or injection payloads, the system SHALL require an explicit confirmation before running negative cases that use such methods, and SHALL surface the target environment so a user does not unintentionally run destructive cases against a production environment. Read-only (safe-method) negative runs SHALL NOT require this confirmation. When the confirmation is for a collection run, the system SHALL present it as a **warning** rather than an error, SHALL explain that state-changing negative payloads will be sent against the target environment, and SHALL make the list of affected requests available **on demand** — collapsed by default and expandable — rather than as an always-expanded block that grows with request count. The affected list SHALL include only requests whose negatives will actually run under the chosen mode: effective negative-testing state on, has cases, and a state-changing method.

#### Scenario: Mutating negative run requires confirmation

- **WHEN** a user starts negative testing for a request whose cases include a state-changing method and has not confirmed
- **THEN** the system SHALL block the run and present the cases and the active environment for confirmation

#### Scenario: Confirmed mutating run proceeds

- **WHEN** a user confirms after being shown the mutating cases and environment
- **THEN** the negative run SHALL proceed

#### Scenario: Safe-method run needs no confirmation

- **WHEN** all of a request's negative cases use read-only methods
- **THEN** the run SHALL proceed without a destructive-run confirmation

#### Scenario: Unconfirmed collection run skips only the state-changing cases

- **WHEN** a collection run executes without destructive confirmation and a request's enabled negative cases mix read-only and state-changing methods
- **THEN** the system SHALL run that request's read-only negative cases and skip only its state-changing cases

#### Scenario: Collection run surfaces the confirmation before running mutating cases

- **WHEN** a user starts a collection run and any request in it would fire state-changing negative cases
- **THEN** the system SHALL present the affected requests and the target environment for confirmation, and run the state-changing cases only once confirmed

#### Scenario: Collection confirmation is a warning with the affected APIs shown on demand

- **WHEN** a collection run would fire state-changing negative cases across one or more requests
- **THEN** the confirmation SHALL be presented as a warning (not a red error) with a message that state-changing payloads will affect the target environment, and the list of affected requests SHALL be collapsed by default and expandable on demand

#### Scenario: Affected list matches what will actually run

- **WHEN** the collection default is off and only some requests have effective-on negatives that use a state-changing method
- **THEN** the confirmation's affected-requests list SHALL contain only those requests and SHALL NOT list requests whose negatives are off or that have no cases

### Requirement: Regeneration diff when the request changes

When a user regenerates negative cases after the underlying request has changed, the system SHALL present the difference between the existing cases and the newly generated set — which cases are newly suggested and which no longer apply — rather than silently discarding a user's edits.

#### Scenario: New fields yield newly suggested cases

- **WHEN** a request gains a new body field and the user regenerates
- **THEN** the system SHALL identify the cases newly suggested for that field without silently overwriting existing edited cases

#### Scenario: Removed fields mark stale cases

- **WHEN** a request drops a field and the user regenerates
- **THEN** the system SHALL identify the cases for the removed field as no longer applicable

### Requirement: Collection-run negatives mode selection

When a user starts a collection run and the collection has negative cases, the system SHALL let the user choose how negatives participate in that run: run everything (happy-path plus negatives as configured), run without negatives (happy-path only), or run only negatives. In the only-negatives mode the system SHALL run negative cases only for requests whose **effective negative-testing state is on** (by request override or inherited collection default) **and** that have generated cases; it SHALL skip any request whose effective state is off, even if that request has cases. In the only-negatives mode the system SHALL suppress the happy-path assertion and schema evaluation so a request's result reflects its negatives alone. When no request in the collection has negative cases, the system SHALL run without presenting the choice.

#### Scenario: Run without negatives skips all negative cases

- **WHEN** a user starts a collection run and chooses to run without negatives
- **THEN** the run SHALL execute each request's happy path and SHALL NOT run any negative cases

#### Scenario: Run only negatives runs solely the effective-on requests with cases

- **WHEN** a user starts a collection run and chooses to run only negatives, and the collection default is off while three requests have an `on` override with generated cases
- **THEN** the run SHALL execute negative cases for exactly those three requests and SHALL NOT run negatives for any request whose effective state is off

#### Scenario: Run only negatives suppresses the happy path

- **WHEN** a user starts a collection run and chooses to run only negatives
- **THEN** for each request whose effective negative-testing state is on and that has cases, the run SHALL execute its negative cases and SHALL NOT let happy-path assertion or schema results affect that request's verdict

#### Scenario: Only-negatives run reports exactly the qualifying requests

- **WHEN** a collection of many requests runs in only-negatives mode and only some requests qualify (effective on with cases)
- **THEN** the run's progress total, its recorded per-request results, the live run view, and the downloadable report SHALL each contain exactly the qualifying requests and no others

#### Scenario: No negatives means no mode choice

- **WHEN** a user starts a collection run for a collection whose requests have no negative cases
- **THEN** the system SHALL run normally without offering a negatives-mode choice

### Requirement: Active negative-testing indicators

The system SHALL indicate at a glance which requests have negative testing active, respecting inheritance. Negative testing is "active" for a request only when its effective negative-testing state is on **and** it has at least one enabled generated case — a request that is on but has no enabled cases behaves as if negative testing were off (nothing runs) and SHALL NOT be marked active. A request that is active SHALL carry a marker in the collection's request list and on the request editor's negative-testing tab, so a user can see which requests run negative testing without opening each one. The marker's visibility SHALL NOT depend on whether the row is selected, hovered, or focused.

#### Scenario: Request list marks a request with negatives active

- **WHEN** a request's effective negative-testing state is on (by its own override or by inheriting an on collection default) and it has at least one enabled case
- **THEN** that request's row in the collection list SHALL show a negative-testing marker

#### Scenario: On without cases is not marked and runs nothing

- **WHEN** a request's effective negative-testing state is on but it has no enabled generated cases
- **THEN** neither the request list row nor the negative-testing tab SHALL show the marker, and no negatives SHALL run for it — it behaves as if negative testing were off

#### Scenario: Editor tab marks the active feature

- **WHEN** a request's effective negative-testing state is on and it has at least one enabled case
- **THEN** the request editor's negative-testing tab SHALL show a marker indicating it is active

#### Scenario: Inactive request shows no marker

- **WHEN** a request's effective negative-testing state is off
- **THEN** neither the request list row nor the negative-testing tab SHALL show the negative-testing marker

#### Scenario: Selected row keeps its negative-testing marker

- **WHEN** an active (on with cases) request is the selected row in the collection list
- **THEN** its negative-testing marker SHALL remain visible and SHALL NOT be hidden or overridden by the selected-row styling

### Requirement: Negative-testing data survives a full cloud-sync round-trip

The system SHALL round-trip negative-testing configuration and verdicts through cloud sync so that a member who pulls another member's data sees the same negative-testing state and results the originator had. This SHALL hold across every sync path, not only the workspace path:

- Push SHALL carry the collection default (`negative_check_default`), each request's negative config (`negative_cases`, `negative_check` override, `field_constraints`), and each executed result's negative verdict (`negative_result`).
- The workspace pull SHALL restore collection defaults and per-request negative config.
- The collection-run-history pull SHALL restore the per-result negative verdict for every request result it merges.

No sync path SHALL silently discard a negative-testing field that was present in the pushed payload. When a pulled result carries no negative verdict (negatives were not run, or an older payload predates the field), the merged result SHALL store an empty verdict rather than fail the pull.

#### Scenario: Per-request negative config survives the workspace round-trip

- **WHEN** a request with a saved collection default, a `negative_check` override, generated `negative_cases`, and `field_constraints` is pushed and then pulled on another machine via the workspace path
- **THEN** the pulled request SHALL carry the same collection default, override, cases, and constraints

#### Scenario: Negative verdict survives the collection-run-history pull

- **WHEN** a collection run whose request results carry `negative_result` verdicts is pushed, and another machine later pulls that run through the collection-run-history path
- **THEN** each merged request result SHALL carry the same `negative_result` verdict the originator recorded

#### Scenario: No path drops a verdict that was pushed

- **WHEN** any pull path merges a request result whose pulled payload includes a `negative_result` verdict
- **THEN** the stored result SHALL retain that verdict, never a null in place of a verdict that was present

#### Scenario: Result without a negative verdict pulls cleanly

- **WHEN** a pulled request result has no `negative_result` (negatives were not run for it, or the payload predates the field)
- **THEN** the merge SHALL succeed and store an empty verdict for that result without error

