## ADDED Requirements

### Requirement: Backgrounded push completion is surfaced to the user
When a push response reports remaining queued items with none yet marked failing, the UI SHALL poll sync status for a bounded period after the push and notify the user of the outcome once the background retry resolves, without falsely claiming success if it does not resolve within that period.

#### Scenario: Backgrounded push later succeeds
- **WHEN** a push leaves items queued but not yet failing, and a subsequent status check within the polling period reports zero items remaining
- **THEN** the UI shows a success notice that the push completed

#### Scenario: Backgrounded push later fails
- **WHEN** a push leaves items queued but not yet failing, and a subsequent status check within the polling period reports one or more failing entities
- **THEN** the UI shows an error-styled notice identifying at least one failing entity and its error message

#### Scenario: Backgrounded push does not resolve within the polling period
- **WHEN** a push leaves items queued but not yet failing, and no status check within the polling period reports either zero remaining or a failing entity
- **THEN** the UI shows no further notice and does not claim the push succeeded

#### Scenario: A new push supersedes an in-progress poll
- **WHEN** the user triggers another push while a completion poll from a previous push is still in progress
- **THEN** the previous poll is cancelled so only one completion notice can fire at a time
