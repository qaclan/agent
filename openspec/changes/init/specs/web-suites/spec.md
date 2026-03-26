## ADDED Requirements

### Requirement: Create a web suite
The system SHALL create a suite with `channel = web` under the active project with a unique ID prefixed `suite_`.

#### Scenario: Create suite successfully
- **WHEN** user runs `qaclan web suite create "Smoke Suite"`
- **THEN** system creates a suite record with channel "web"
- **THEN** system prints `✓ Suite created: Smoke Suite [suite_<id>]  [WEB]`

### Requirement: Add script to suite
The system SHALL add a script to a suite with an auto-incremented order index. Only web scripts SHALL be added to web suites.

#### Scenario: Add script to suite
- **WHEN** user runs `qaclan web suite add --suite suite_abc --script script_001`
- **THEN** system creates a suite_item with the next order_index

#### Scenario: Script channel mismatch
- **WHEN** user tries to add an API script to a web suite
- **THEN** system rejects with an appropriate error

### Requirement: Reorder scripts in suite
The system SHALL rewrite order indices to match the provided script order.

#### Scenario: Reorder scripts
- **WHEN** user runs `qaclan web suite reorder --suite suite_abc --scripts script_002,script_001,script_003`
- **THEN** system updates order_index values: script_002=0, script_001=1, script_003=2

### Requirement: Remove script from suite
The system SHALL remove a script from a suite without deleting the script itself.

#### Scenario: Remove script from suite
- **WHEN** user runs `qaclan web suite remove --suite suite_abc --script script_002`
- **THEN** system deletes the suite_item record

### Requirement: Show suite details
The system SHALL display suite contents with ordered scripts, feature names, and run history.

#### Scenario: Show suite
- **WHEN** user runs `qaclan web suite show --suite suite_abc`
- **THEN** system displays a tree of scripts with order, name, ID, and feature
- **THEN** system shows first run date, last run date, and last run status

### Requirement: List web suites
The system SHALL display all web suites with script counts and last run info.

#### Scenario: List suites
- **WHEN** user runs `qaclan web suite list`
- **THEN** system displays a table with columns: ID, Name, Scripts, Last Run, Status

### Requirement: Delete a suite
The system SHALL delete a suite and its suite_items after confirmation.

#### Scenario: Delete suite
- **WHEN** user runs `qaclan web suite delete suite_abc` and confirms
- **THEN** system deletes the suite and all suite_items (but not the scripts themselves)
