# collection-runtime-variables Specification

## Purpose

Defines how a script's `qc.set` output is persisted as a collection variable's runtime value, scoped to the environment active when it was captured, so it never masquerades as a stale value under a different or absent environment and never overwrites the user's static default.

## Requirements

### Requirement: A script-captured value is tagged with the environment active at capture time
When a pre-script or post-script calls `qc.set(key, value)`, the system SHALL persist that value as the collection variable's runtime value tagged with the environment bound to the collection at the moment the script ran.

#### Scenario: Script runs with an environment bound
- **WHEN** a post-script calls `qc.set('access_token', token)` while environment "dev" is bound to the collection
- **THEN** the collection variable `access_token` records a runtime value tagged as captured under "dev"

#### Scenario: Script runs with no environment bound
- **WHEN** a post-script calls `qc.set(key, value)` while the collection has no environment bound
- **THEN** the recorded runtime value is tagged as captured under "no environment"

### Requirement: A script-captured runtime value never overwrites the static default
The collection variable's user-authored static default value SHALL remain unchanged by any `qc.set` call; the static default and the script-captured runtime value SHALL be stored separately.

#### Scenario: Script overwrites a variable that also has a static default
- **WHEN** a collection variable `access_token` has a static default value and a script later calls `qc.set('access_token', newToken)`
- **THEN** the static default value is unchanged and remains visible/recoverable, while the runtime value reflects `newToken`

### Requirement: A runtime value is used only when its captured environment matches the currently bound environment
When resolving a collection variable's current value for a run, the system SHALL use the runtime value only if the environment it was tagged with matches the environment currently bound to the collection; otherwise the system SHALL fall back to the static default (or treat the variable as unset if no static default exists).

#### Scenario: Same environment still bound
- **WHEN** a runtime value was captured under environment "dev" and "dev" is still the collection's bound environment
- **THEN** the runtime value is used to resolve the variable

#### Scenario: A different environment is now bound
- **WHEN** a runtime value was captured under environment "dev" and the collection's bound environment is later changed to "staging"
- **THEN** the runtime value is not used, and the variable resolves to its static default (or is treated as unset)

#### Scenario: The environment is unbound
- **WHEN** a runtime value was captured under environment "dev" and the collection's environment is later unbound (set to none)
- **THEN** the runtime value is not used, and the variable resolves to its static default (or is treated as unset)

#### Scenario: A runtime value captured with no environment bound is later reused
- **WHEN** a runtime value was captured while no environment was bound and the collection still has no environment bound
- **THEN** the runtime value is used to resolve the variable

### Requirement: The variable picker distinguishes a runtime override from the static default
Wherever a collection variable's current value is shown for editing or insertion, the system SHALL indicate when that value is an active script-captured runtime override (and which environment it was captured under) as distinct from the static default.

#### Scenario: Variable has an active runtime override
- **WHEN** the user views a collection variable whose runtime value is currently applying (its captured environment matches the bound environment)
- **THEN** the picker indicates the value came from a script run under that environment, distinct from the static default

#### Scenario: Variable has no active runtime override
- **WHEN** the user views a collection variable whose runtime value (if any) does not match the currently bound environment
- **THEN** the picker shows only the static default as the current value, without implying a script recently set it
