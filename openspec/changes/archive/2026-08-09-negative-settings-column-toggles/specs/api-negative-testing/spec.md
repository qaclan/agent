## MODIFIED Requirements

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
