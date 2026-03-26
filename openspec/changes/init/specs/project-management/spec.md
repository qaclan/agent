## ADDED Requirements

### Requirement: Create a project
The system SHALL create a new project with a unique ID (prefixed `proj_`) and set it as the active project in config.json.

#### Scenario: Create project successfully
- **WHEN** user runs `qaclan project create "Voxcruit"`
- **THEN** system creates a project record with name "Voxcruit" and a generated ID
- **THEN** system sets the project as active in `~/.qaclan/config.json`
- **THEN** system prints confirmation: `✓ Project created: Voxcruit [proj_<id>]` and `Active project set to: Voxcruit`

### Requirement: List all projects
The system SHALL display all projects in a table with ID, name, and creation date.

#### Scenario: List projects
- **WHEN** user runs `qaclan project list`
- **THEN** system displays a table with columns: ID, Name, Created
- **THEN** all projects are shown sorted by creation date

#### Scenario: No projects exist
- **WHEN** user runs `qaclan project list` and no projects exist
- **THEN** system prints a message suggesting `qaclan project create "name"`

### Requirement: Switch active project
The system SHALL update config.json to set a different project as active.

#### Scenario: Switch to existing project
- **WHEN** user runs `qaclan project use proj_abc123` and the project exists
- **THEN** system updates config.json and prints `✓ Active project: Voxcruit`

#### Scenario: Switch to non-existent project
- **WHEN** user runs `qaclan project use proj_invalid` and the project does not exist
- **THEN** system prints error suggesting `qaclan project list`

### Requirement: Show active project
The system SHALL display the currently active project.

#### Scenario: Show active project
- **WHEN** user runs `qaclan project show` and an active project is set
- **THEN** system prints `Active project: Voxcruit [proj_abc123]`

#### Scenario: No active project
- **WHEN** user runs `qaclan project show` and no active project is set
- **THEN** system prints `No active project. Run: qaclan project create "name"`
