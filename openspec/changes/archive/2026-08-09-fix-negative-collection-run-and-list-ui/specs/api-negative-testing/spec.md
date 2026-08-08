## MODIFIED Requirements

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
