## ADDED Requirements

### Requirement: List all runs
The system SHALL display all suite runs for the active project in a table.

#### Scenario: List runs
- **WHEN** user runs `qaclan runs`
- **THEN** system displays a table with columns: Run ID, Suite, Channel, Status, Scripts (passed/total), Started, Duration

#### Scenario: Filter runs by suite
- **WHEN** user runs `qaclan runs --suite suite_abc123`
- **THEN** system displays only runs for that suite

#### Scenario: No runs exist
- **WHEN** user runs `qaclan runs` and no runs exist
- **THEN** system prints a message suggesting how to create and run a suite

### Requirement: Show run details
The system SHALL display detailed per-script results for a specific run.

#### Scenario: Show run details
- **WHEN** user runs `qaclan run show run_abc123`
- **THEN** system prints run header: run ID, suite name, channel, status
- **THEN** system prints started time, duration, environment name
- **THEN** system lists each script with order, name, status, duration, and console error count
- **THEN** failed scripts show their error message indented below

#### Scenario: Run not found
- **WHEN** user runs `qaclan run show run_invalid`
- **THEN** system prints an error suggesting `qaclan runs`
