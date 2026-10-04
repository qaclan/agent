## Purpose

Records the timeouts each run actually used and reports timeout failures precisely, so a failure can be explained after settings change and points at the right setting to adjust.

## ADDED Requirements

### Requirement: Suite run snapshot
Each suite run SHALL store a snapshot of its timeout configuration: the run dialog pick, the resolved wait limit, the test timeout mode (auto or fixed), the max script time, and the level (script, run, suite, project, built-in) each value came from.

#### Scenario: Snapshot written
- **WHEN** a suite run starts with suite wait limit 15s, auto test timeout and project max script time 280s
- **THEN** its snapshot records wait limit 15000 from suite, mode auto, max script time 280000 from project

### Requirement: Script run effective values
Each script run SHALL store its effective wait limit and effective test timeout. For strategies with no per-test timeout the effective test timeout SHALL be NULL.

#### Scenario: Test strategy
- **WHEN** a `javascript_test` script with 20 actions runs under defaults
- **THEN** its record has effective test timeout 130000

#### Scenario: Raw strategy
- **WHEN** a `python` script runs
- **THEN** its effective test timeout is NULL

### Requirement: Run detail display
Run detail SHALL show the recorded configuration in plain words, such as "wait limit 15s from suite, test timeout 130s auto, max script time 280s from project". Runs recorded before this change SHALL display without error and without the line.

#### Scenario: Old run
- **WHEN** a user opens a run created before this change
- **THEN** the detail renders normally and shows no timeout line

### Requirement: Timeout failure classification
The error classifier SHALL distinguish three failures: a per-test timeout (`Test timeout of Nms exceeded`), an expect or action timeout, and the max-script-time subprocess kill. Each SHALL carry a `next_step` pointing at the matching setting, and the kill message SHALL state the actual limit used.

#### Scenario: Test timeout
- **WHEN** a script fails with `Test timeout of 90000ms exceeded`
- **THEN** it is classified as a test timeout and the next step suggests raising the test timeout or max script time

#### Scenario: Expect timeout
- **WHEN** a script fails on an expect timing out at the wait limit
- **THEN** it is classified separately and the next step points at the wait limit

#### Scenario: Subprocess kill
- **WHEN** a script is killed at max script time plus 20 s
- **THEN** it is classified as a max-script-time kill naming the actual limit
