## Purpose

Keeps project and suite timeout settings, and script wait limits, consistent between the local agent and qaclan.com so a fresh machine recovers them on pull.

## ADDED Requirements

### Requirement: Push project and suite settings
Saving project or suite timeout settings SHALL enqueue a cloud sync. A synced project or suite payload SHALL include each of `wait_timeout`, `test_timeout` and `max_script_time` only when its value is not NULL, so untouched projects and suites send the same payload as before.

#### Scenario: Settings saved
- **WHEN** a user saves a suite `wait_timeout` of 30000
- **THEN** a suite upsert is queued and the payload carries `wait_timeout` 30000

#### Scenario: Untouched project
- **WHEN** a project has all three settings unset and is synced
- **THEN** its payload contains none of the three keys

### Requirement: Pull project and suite settings
Pulling SHALL set each of the three fields on the local project or suite when the key is present in the payload, with null clearing the local value. When the key is absent the local value SHALL be left unchanged.

#### Scenario: Round trip on a fresh machine
- **WHEN** settings were pushed, the local database is wiped, and a pull runs
- **THEN** the project and suite settings are restored

#### Scenario: Older cloud response
- **WHEN** a pulled payload omits the three keys
- **THEN** local settings survive

#### Scenario: Explicit null
- **WHEN** a pulled payload has `test_timeout` null
- **THEN** the local test timeout becomes unset

### Requirement: Pull script wait limit
Pulling a script SHALL restore its `wait_timeout` on both insert and update.

#### Scenario: Pull on fresh machine
- **WHEN** a script with `wait_timeout` 45000 was pushed and a pull runs on an empty database
- **THEN** the local script has `wait_timeout` 45000

### Requirement: Sync stays best-effort
Failure to sync timeout settings SHALL NOT block saving them locally and SHALL NOT fail the local operation.

#### Scenario: Cloud unreachable
- **WHEN** a user saves project settings while the cloud is unreachable
- **THEN** the local save succeeds and settings remain effective for local runs
