## Purpose

Lets users configure wait limit, test timeout and max script time once at project level and override them per suite, so timeout budgets are managed where tests are organized instead of per run.

## ADDED Requirements

### Requirement: Project timeout settings
Each project SHALL store optional `wait_timeout`, `test_timeout` and `max_script_time` values in milliseconds. A NULL value SHALL mean "not set": wait limit and max script time fall through to the built-in default, and a NULL test timeout means auto.

#### Scenario: New project has no overrides
- **WHEN** a project is created
- **THEN** all three settings are unset and runs behave as with built-in defaults

#### Scenario: Existing data survives upgrade
- **WHEN** the agent starts against a database created before this change
- **THEN** existing projects and suites gain the settings as unset, and no existing run is altered

### Requirement: Suite timeout settings
Each suite SHALL store the same three optional settings. An unset suite value SHALL inherit the project value.

#### Scenario: Suite inherits project
- **WHEN** a project sets `max_script_time` 400000 and a suite leaves it unset
- **THEN** the suite's effective max script time is 400000 ms

#### Scenario: Suite overrides project
- **WHEN** a suite sets `wait_timeout` 30000 and its project sets 10000
- **THEN** the suite's effective wait limit is 30000 ms

### Requirement: Validation
The system SHALL reject a save that violates: wait limit not in {5000, 10000, 15000, 30000, 45000, 60000}; max script time not an integer from 60000 to 1800000; fixed test timeout not an integer from 30000 up to the resolved max script time. Rejection SHALL return a clear error and leave stored values unchanged.

#### Scenario: Invalid wait limit
- **WHEN** a save sends `wait_timeout` 12345
- **THEN** the save is rejected with an error naming the allowed values and nothing is stored

#### Scenario: Fixed test timeout above cap
- **WHEN** a suite sets max script time 120000 and test timeout 200000
- **THEN** the save is rejected because test timeout exceeds max script time

#### Scenario: Clearing a value
- **WHEN** a save sends null for a setting
- **THEN** the stored value becomes unset

### Requirement: Project settings API and page
The system SHALL expose reading and updating a project's three timeout settings, and a "Project settings" page reachable from the project dropdown with a single "Timeouts" section. The suite update operation SHALL accept the three suite settings alongside rename.

#### Scenario: Save project settings
- **WHEN** a user sets wait limit 30s in the Timeouts section and saves
- **THEN** the value persists and a reload of the page shows it

#### Scenario: Rename without touching settings
- **WHEN** a suite update contains only a new name
- **THEN** the suite's timeout settings are unchanged

### Requirement: Suite settings inputs
The suite settings UI SHALL provide the three inputs, each with a one-line description, a short example, and an "Inherit project default (value)" choice, and SHALL explain the test, action, expect and navigation budgets.

#### Scenario: Inherit choice shows value
- **WHEN** the project wait limit is 30s and a suite has none
- **THEN** the suite's wait limit input reads "Inherit project default (30s)"

### Requirement: Run dialog default option
The run dialog wait-limit select SHALL offer "Use suite default (Ns)" as its first and default option, which sends no wait limit. Choosing a number SHALL be a one-off override for that run only.

#### Scenario: Default option sends nothing
- **WHEN** a user runs a suite with the dialog left on "Use suite default"
- **THEN** the run request carries no wait limit and the resolution chain decides

#### Scenario: One-off override
- **WHEN** a user picks 10s in the dialog
- **THEN** that run uses 10 s where no script override exists, and the suite's stored setting is unchanged
