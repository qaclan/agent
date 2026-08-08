## ADDED Requirements

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
