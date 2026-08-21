# sync-queue-diagnostics Specification

## Purpose

Gives users visibility into cloud-sync items that are stuck failing (with the reason) instead of retrying silently forever, and stops dependent entities from repeatedly re-attempting a parent that is already known to be broken.

## Requirements

### Requirement: Sync status exposes failing entities
The sync status endpoint SHALL include a list of currently-failing sync-queue entries, each identifying the entity type, a human-readable label for the entity, its attempt count, and its most recent error message.

#### Scenario: Status requested while entities are failing
- **WHEN** a client requests sync status and one or more queued entities have a non-zero attempt count
- **THEN** the response includes, for each such entity, its type, a human-readable label, attempt count, and last error message

#### Scenario: Status requested with nothing failing
- **WHEN** a client requests sync status and no queued entities have a non-zero attempt count
- **THEN** the response's failing-entities list is empty

### Requirement: Push response reports failing entities inline
Triggering a push SHALL report the same failing-entity detail as the status endpoint for any items that remain queued after the push attempt, not just a bare remaining-count.

#### Scenario: Push leaves failing items behind
- **WHEN** a push completes and one or more remaining queued items have a non-zero attempt count
- **THEN** the push response includes each such item's type, label, attempt count, and last error message

#### Scenario: Push leaves only not-yet-attempted items behind
- **WHEN** a push completes and remaining queued items exist but none have been attempted yet
- **THEN** the push response reports the remaining count without listing them as failing

### Requirement: Push failures are visibly distinguished in the UI
When a push response reports failing entities, the UI SHALL present a notice that is visibly distinct from the generic "still pending, will retry" notice, naming the failing entity and its error.

#### Scenario: User pushes and a failing entity is reported
- **WHEN** the push response includes one or more failing entities
- **THEN** the UI shows an error-styled notice identifying at least one failing entity and its error message, instead of the generic pending notice

#### Scenario: User pushes and only not-yet-attempted items remain
- **WHEN** the push response reports remaining items with none marked failing
- **THEN** the UI shows the existing generic "still pending, will retry" notice

### Requirement: Dependent entities short-circuit around a known-broken parent
When dispatching a queued entity whose parent entity has its own queued failure recorded within a cooldown window, the system SHALL mark the dependent as failed with an error indicating it is blocked on the parent's failure, without issuing a duplicate sync attempt for the parent.

#### Scenario: Child dispatched while parent is recently broken
- **WHEN** a queued entity is dispatched and its parent entity has a queued failure with a last-attempt time inside the cooldown window
- **THEN** the child is recorded as failed with an error referencing the parent's failure, and no new sync request is sent for the parent

#### Scenario: Child dispatched after parent's cooldown has elapsed
- **WHEN** a queued entity is dispatched and its parent's last recorded failure is older than the cooldown window
- **THEN** the system attempts to sync the parent again as before
