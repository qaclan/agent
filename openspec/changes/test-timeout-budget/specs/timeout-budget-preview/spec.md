## Purpose

Shows, before running, how much time a suite is allowed to take and which scripts are at risk, using the same budget the runner applies.

## ADDED Requirements

### Requirement: Preview endpoint
The system SHALL provide a per-suite timeout preview returning, for each script, its name, strategy, action count, settle count, wait limit and source, test timeout, typical estimate and worst-case estimate, plus a summary. The preview SHALL accept unsaved wait limit, test timeout and max script time values so edits can be previewed before saving.

#### Scenario: Preview matches run
- **WHEN** the preview is requested for a suite and the suite is then run with the same settings
- **THEN** each script's previewed wait limit and test timeout equal the values the run records

#### Scenario: Unsaved edits
- **WHEN** the preview is requested with a max script time that differs from the stored one
- **THEN** the response reflects the supplied value and nothing is stored

### Requirement: Worst-case estimate
The worst-case estimate SHALL assume every network settle runs to its own 15 s soft cap, and SHALL be flagged when it exceeds the max script time.

#### Scenario: Over cap
- **WHEN** a script's worst case exceeds the max script time
- **THEN** its row is flagged as over cap

### Requirement: Suite settings panel
The suite settings panel SHALL list one row per script with a bar comparing its test timeout to the max script time and, where history exists, a marker for the last real run duration. It SHALL show suite total (sum of test timeouts), the longest script, and warnings for scripts whose worst case exceeds the cap or whose last run used more than 80% of its budget. Strategies with no per-test timeout SHALL show "limited only by max script time".

#### Scenario: Near-budget warning
- **WHEN** a script's last run used 85% of its test timeout
- **THEN** the panel shows a warning on that script

#### Scenario: No history
- **WHEN** a script has never run
- **THEN** its row shows no duration marker and no near-budget warning

#### Scenario: Fixed timeout above reduced cap
- **WHEN** a suite lowers max script time below a project fixed test timeout
- **THEN** the panel warns that the test timeout will be clamped

### Requirement: Run dialog summary
The run dialog SHALL show one summary line with the suite total and longest script, linking to the settings panel.

#### Scenario: Summary shown
- **WHEN** a user opens the run dialog for a suite
- **THEN** a line states the suite total and longest script budget and links to the panel
