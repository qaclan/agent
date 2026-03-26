## ADDED Requirements

### Requirement: Show project status overview
The system SHALL display the full project state grouped by channel, showing features, scripts, and warnings.

#### Scenario: Status with web features and scripts
- **WHEN** user runs `qaclan status` and the active project has web features
- **THEN** system prints project name
- **THEN** system prints WEB section with each feature, its script count, and listed scripts with IDs
- **THEN** features with 0 scripts show a warning: `⚠ no scripts recorded`

#### Scenario: Status with no API features
- **WHEN** user runs `qaclan status` and no API features exist
- **THEN** API section prints `No API features yet. Run 'qaclan api feature create "name"' to start.`

#### Scenario: Status summary line
- **WHEN** user runs `qaclan status`
- **THEN** system prints a summary line: `X web scripts across Y features. Z features have no scripts.`

#### Scenario: No active project
- **WHEN** user runs `qaclan status` with no active project
- **THEN** system prints `No active project. Run: qaclan project create "name"`
