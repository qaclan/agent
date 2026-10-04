## Purpose

Defines how the time a script run is allowed to take is resolved and enforced: the wait limit, the per-test timeout, and the max script time. One consistent budget applies to suite runs and solo script runs.

## ADDED Requirements

### Requirement: Wait limit resolution
The system SHALL resolve the wait limit (applied to both expect and action timeouts) from the first defined value in this order: script `wait_timeout`, run dialog pick, suite `wait_timeout`, project `wait_timeout`, built-in default of 15000 ms. A solo script run has no suite and no run dialog pick, so it SHALL resolve script, project, built-in default.

#### Scenario: Suite default applies when nothing higher is set
- **WHEN** a suite has `wait_timeout` 30000, the script has no override, and the run dialog is left on "Use suite default"
- **THEN** the script runs with expect and action timeouts of 30000 ms

#### Scenario: Run dialog pick beats suite default
- **WHEN** a suite has `wait_timeout` 30000 and the user picks 10s in the run dialog
- **THEN** scripts without their own override run with 10000 ms

#### Scenario: Script override beats everything
- **WHEN** a script has `wait_timeout` 45000 and the run dialog pick is 10s
- **THEN** that script runs with 45000 ms

#### Scenario: Solo run honors script and project values
- **WHEN** a script with `wait_timeout` 30000 is run on its own
- **THEN** it runs with 30000 ms rather than a hardcoded value, and a script with no override uses the project value, then 15000 ms

### Requirement: Max script time resolution
The system SHALL resolve max script time from the first defined value of suite `max_script_time`, project `max_script_time`, built-in default of 280000 ms. A solo script run has no suite, so it SHALL resolve project, then built-in default. Accepted values SHALL be integers from 60000 to 1800000 ms.

#### Scenario: Suite beats project
- **WHEN** a project has `max_script_time` 300000 and its suite has 120000
- **THEN** scripts in that suite run with a max script time of 120000 ms

#### Scenario: Built-in default
- **WHEN** neither suite nor project sets a max script time
- **THEN** the max script time is 280000 ms

### Requirement: Derived subprocess kill
The system SHALL kill a script subprocess only after the resolved max script time plus 20 seconds, so the in-process test timeout fires first. The system SHALL NOT use a fixed 300 s constant for the kill, the "timed out after Ns" message, or the classifier text.

#### Scenario: Default kill time
- **WHEN** no max script time is configured
- **THEN** a hung script subprocess is killed after 300 s and the message states the actual limit used

#### Scenario: Custom max script time
- **WHEN** max script time resolves to 600000 ms
- **THEN** the subprocess is killed after 620 s and the timeout message and classifier text report that value

### Requirement: Auto test timeout
For `javascript_test` and `typescript_test` scripts, when no fixed test timeout is configured, the system SHALL compute the test timeout as `min(cap, max(floor, 30 s + 5 s × n_actions))`, where `floor` is `max(expect, action) + 60 s`, `cap` is the resolved max script time, and `n_actions` counts goto, click, fill, selectOption, check/uncheck, press, hover and dblclick statements in the script's action block. The floor SHALL ensure no script gets a shorter test timeout than the previous flat `max(expect, action) + 60 s`.

#### Scenario: Short script keeps old budget
- **WHEN** a script has 5 actions and a 15 s wait limit
- **THEN** its test timeout is 75 s (the floor), since 30 s + 5 s × 5 = 55 s is below it

#### Scenario: Long script scales
- **WHEN** a script has 20 actions, a 15 s wait limit, and a 280 s cap
- **THEN** its test timeout is 130 s

#### Scenario: Cap holds very long script
- **WHEN** a script has 60 actions and the cap is 280 s
- **THEN** its test timeout is 280 s

### Requirement: Fixed test timeout
When a fixed test timeout is configured (suite first, then project), the system SHALL use it instead of the auto value. A fixed test timeout SHALL be an integer of at least 30000 ms and SHALL NOT exceed the resolved max script time. If a lower level later reduces the max script time below a fixed test timeout, the system SHALL clamp the test timeout to the max script time at run time.

#### Scenario: Fixed value used
- **WHEN** a suite has a fixed test timeout of 200000 ms and max script time is 280000 ms
- **THEN** its `javascript_test` scripts run with a 200000 ms test timeout regardless of action count

#### Scenario: Clamp after cap reduction
- **WHEN** the project fixed test timeout is 250000 ms and the suite lowers max script time to 120000 ms
- **THEN** scripts in that suite run with a 120000 ms test timeout

### Requirement: Test timeout delivery
The system SHALL pass the resolved test timeout to `javascript_test` and `typescript_test` scripts via `QACLAN_TEST_TIMEOUT`. When it is unset the generated config SHALL fall back to the previous flat `max(expect, action) + 60 s`. Strategies with no per-test timeout (`python`, `javascript`, `typescript`) SHALL be limited only by the max script time.

#### Scenario: Env var consumed
- **WHEN** a `javascript_test` script runs with a resolved test timeout of 130000 ms
- **THEN** its Playwright config uses a 130000 ms test timeout

#### Scenario: Raw playwright script unchanged
- **WHEN** a `python` script runs
- **THEN** no per-test timeout is applied and only the derived subprocess kill limits it

### Requirement: Solo run correctness
The solo script run SHALL use the same resolution as suite runs and SHALL complete without error when reading run artifacts.

#### Scenario: Solo run succeeds
- **WHEN** a user runs a single script on its own
- **THEN** the run completes and records artifacts without an unpack error
