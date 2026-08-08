## Purpose

Detects when an API response's structural shape drifts from a previously accepted "baseline", so testers learn about contract changes (removed fields, changed types, new fields) without having to hand-author an assertion for every field.

## ADDED Requirements

### Requirement: Opt-in schema check with collection-default master switch

The system SHALL let a user enable a response schema check without it being on by default. Enablement SHALL follow an inheritance model: a collection carries a default schema-check state (on or off), and each request carries an override with three states — inherit, on, off. The effective state for a run SHALL be the request override when it is `on` or `off`, otherwise the collection default. Changing the collection default SHALL act as a master switch: it SHALL reset every request's override in that collection to `inherit`, so all requests follow the new default. A user MAY re-apply a per-request override afterward.

#### Scenario: Default is off for a new request in a collection with default off

- **WHEN** a request has an `inherit` override and its collection default is off
- **THEN** the schema check SHALL NOT run for that request

#### Scenario: Collection default on cascades by inheritance

- **WHEN** a collection default is set to on and a request has an `inherit` override
- **THEN** the schema check SHALL run for that request

#### Scenario: Request override wins over collection default between toggles

- **WHEN** a request override is `off` and its collection default is on, with no collection-default change since the override was set
- **THEN** the schema check SHALL NOT run for that request

#### Scenario: Changing the collection default overwrites all overrides

- **WHEN** a collection default is changed while some requests have explicit `on` or `off` overrides
- **THEN** every request's override in that collection SHALL be reset to `inherit` and all requests SHALL follow the new collection default

### Requirement: Response schema baseline — capture, freeze, and update

The drift baseline is the request's stored response schema. When none is stored yet, the system SHALL capture the schema inferred from the first successful JSON response as the baseline and SHALL treat that first run as having no drift. A baseline seeded earlier (for example from traffic import) SHALL be used as-is. Once a baseline exists, the system SHALL keep it frozen — an ordinary send SHALL NOT overwrite it. The system SHALL provide a manual action ("Update response schema") to re-accept the current response's schema as the new baseline. A response that is not JSON SHALL NOT be captured as, or overwrite, a baseline.

#### Scenario: First JSON response becomes the baseline

- **WHEN** a schema check is active, no baseline is stored, and a request returns a JSON body
- **THEN** the system SHALL store that response's inferred schema as the baseline and report no drift for that run

#### Scenario: Existing baseline is not overwritten by later sends

- **WHEN** a baseline is already stored and the request is sent again with a differently-shaped response
- **THEN** the stored baseline SHALL remain unchanged and the run SHALL be compared against it

#### Scenario: Manual update replaces the baseline

- **WHEN** a user invokes "Update response schema" on a response
- **THEN** the current response's inferred schema SHALL replace the stored baseline and subsequent runs SHALL compare against it

#### Scenario: Non-JSON response does not establish a baseline

- **WHEN** a schema check is active, no baseline is stored, and a request returns a non-JSON body
- **THEN** the system SHALL NOT store a baseline and SHALL report the check as skipped

### Requirement: Structural drift detection with severity classification

When a schema check is active and a baseline exists, the system SHALL compare the inferred schema of the current response against the baseline and classify each difference by severity. Breaking differences SHALL include: a field present in the baseline is absent from the current response; a field's type changed; a field's value became nullable when it was previously non-nullable; an array's element type changed. Additive differences SHALL include: a field present in the current response is absent from the baseline. Each reported difference SHALL identify the field path, the kind of change, and its severity.

#### Scenario: Removed field is breaking

- **WHEN** the baseline contains `data.email` and the current response omits it
- **THEN** the difference SHALL be reported at path `data.email` as a removed field with breaking severity

#### Scenario: Type change is breaking

- **WHEN** `data.age` is a number in the baseline and a string in the current response
- **THEN** the difference SHALL be reported at path `data.age` as a type change with breaking severity

#### Scenario: New field is additive

- **WHEN** the current response contains `data.nickname` and the baseline does not
- **THEN** the difference SHALL be reported at path `data.nickname` as an added field with additive severity

#### Scenario: Identical shapes report no drift

- **WHEN** the current response's inferred schema equals the baseline
- **THEN** the system SHALL report no differences

### Requirement: Severity-based run verdict

The system SHALL fail a request run when the schema check reports at least one breaking difference. The system SHALL keep a request run passing when the schema check reports only additive differences or none. A schema-check failure SHALL be distinguishable in results from an assertion failure. When the schema check is skipped (not enabled, no baseline yet, or non-JSON response), it SHALL NOT change the run verdict.

#### Scenario: Breaking difference fails the run

- **WHEN** the schema check reports one or more breaking differences
- **THEN** the request run status SHALL be failed and the result SHALL indicate a schema-check failure

#### Scenario: Only additive differences keep the run passing

- **WHEN** the schema check reports only additive differences
- **THEN** the request run SHALL remain passing and the additive drift SHALL still be reported to the user

#### Scenario: Skipped check does not affect verdict

- **WHEN** the schema check is skipped because no baseline exists yet
- **THEN** the run verdict SHALL be determined solely by assertions and status code, as if the check were absent

### Requirement: Schema comparison view

When drift is detected, the system SHALL present a comparison view that shows the baseline and the current response schema together, marking each field as unchanged, added, removed, or type-changed, and visually distinguishing breaking from additive changes. The view SHALL be reachable from the response display of a single send.

#### Scenario: Comparison view lists each change with its marker

- **WHEN** a user opens the schema comparison view after a run with drift
- **THEN** the view SHALL show every added, removed, and type-changed field with a marker identifying the change kind and severity

#### Scenario: No comparison offered when there is no baseline

- **WHEN** a run captured the first baseline and reported no drift
- **THEN** the comparison view SHALL indicate there is nothing to compare rather than showing spurious changes

### Requirement: Drift notification and history persistence

After a single send, the system SHALL surface a drift notification summarizing the count and worst severity of differences. In a collection run, each request result SHALL carry a drift indicator visible per request. Drift verdicts SHALL be persisted with run history so that a past run's schema drift can be reviewed after the fact.

#### Scenario: Send surfaces a drift summary

- **WHEN** a single send completes with drift
- **THEN** the user SHALL see a notification stating how many fields changed and whether any change is breaking

#### Scenario: Collection run marks drifted requests

- **WHEN** a collection run includes a request whose schema check reported drift
- **THEN** that request's row SHALL display a drift marker reflecting the worst severity

#### Scenario: Past run retains its drift verdict

- **WHEN** a user reviews a completed run in history
- **THEN** the stored schema-drift verdict for each request SHALL be available for review
