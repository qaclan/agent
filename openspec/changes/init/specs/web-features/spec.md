## ADDED Requirements

### Requirement: Create a web feature
The system SHALL create a feature with `channel = web` under the active project with a unique ID prefixed `feat_`.

#### Scenario: Create feature successfully
- **WHEN** user runs `qaclan web feature create "Authenticate User"`
- **THEN** system creates a feature record with channel "web" linked to the active project
- **THEN** system prints `✓ Feature created: Authenticate User [feat_<id>]  [WEB]`

#### Scenario: No active project
- **WHEN** user runs `qaclan web feature create "name"` with no active project
- **THEN** system prints `No active project. Run: qaclan project create "name"`

### Requirement: List web features
The system SHALL display all web features for the active project with script counts.

#### Scenario: List features with scripts
- **WHEN** user runs `qaclan web feature list`
- **THEN** system displays a table with columns: ID, Name, Scripts (count)
- **THEN** features with 0 scripts show a warning indicator

### Requirement: Delete a web feature
The system SHALL delete a feature after confirmation, warning if scripts are attached.

#### Scenario: Delete feature with scripts
- **WHEN** user runs `qaclan web feature delete feat_abc123` and the feature has scripts
- **THEN** system warns about attached scripts and asks for confirmation
- **THEN** on confirmation, deletes the feature and its associated scripts

#### Scenario: Feature not found
- **WHEN** user runs `qaclan web feature delete feat_invalid`
- **THEN** system prints `Feature feat_invalid not found. Run: qaclan web feature list`
