## ADDED Requirements

### Requirement: List web scripts
The system SHALL display all web scripts for the active project with feature names and source.

#### Scenario: List all scripts
- **WHEN** user runs `qaclan web script list`
- **THEN** system displays a table with columns: ID, Name, Feature, Source

#### Scenario: List scripts filtered by feature
- **WHEN** user runs `qaclan web script list --feature feat_abc123`
- **THEN** system displays only scripts belonging to that feature

### Requirement: Show script content
The system SHALL print the raw content of a script file to the terminal.

#### Scenario: Show script
- **WHEN** user runs `qaclan web script show script_abc123`
- **THEN** system reads `~/.qaclan/scripts/script_abc123.py` and prints its content

#### Scenario: Script not found
- **WHEN** user runs `qaclan web script show script_invalid`
- **THEN** system prints `Script script_invalid not found. Run: qaclan web script list`

### Requirement: Import an external script
The system SHALL copy an external Python file into the scripts directory and register it under a feature.

#### Scenario: Import script successfully
- **WHEN** user runs `qaclan web script import ./test.py --name "Existing test" --feature feat_abc123`
- **THEN** system copies the file to `~/.qaclan/scripts/<script_id>.py`
- **THEN** system creates a script record with `source = UPLOADED`

#### Scenario: Missing feature flag
- **WHEN** user runs `qaclan web script import ./test.py --name "Test"` without `--feature`
- **THEN** system requires the `--feature` option

### Requirement: Delete a script
The system SHALL delete a script after confirmation, warning if it belongs to any suite.

#### Scenario: Delete script in a suite
- **WHEN** user runs `qaclan web script delete script_abc123` and the script is in one or more suites
- **THEN** system warns about suite membership and asks for confirmation
- **THEN** on confirmation, removes the script from suites and deletes the script record and file

#### Scenario: Delete script not in any suite
- **WHEN** user runs `qaclan web script delete script_abc123` and the script is not in any suite
- **THEN** system asks for confirmation and deletes the script record and file
