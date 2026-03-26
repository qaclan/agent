## ADDED Requirements

### Requirement: Initialize storage directory on first use
The system SHALL create `~/.qaclan/` with subdirectories and database on first command invocation.

#### Scenario: First run creates storage
- **WHEN** user runs any qaclan command for the first time
- **THEN** system creates `~/.qaclan/` directory
- **THEN** system creates `~/.qaclan/scripts/` directory
- **THEN** system creates `~/.qaclan/qaclan.db` with all tables
- **THEN** system creates `~/.qaclan/config.json` with empty active_project

### Requirement: Database schema creation
The system SHALL create all 11 tables (projects, features, scripts, environments, env_vars, suites, suite_items, suite_runs, script_runs, step_runs) using CREATE TABLE IF NOT EXISTS.

#### Scenario: Tables created idempotently
- **WHEN** the database already exists with all tables
- **THEN** system does not error on re-initialization

### Requirement: Config file stores active project
The system SHALL read and write active project ID from `~/.qaclan/config.json`.

#### Scenario: Read active project
- **WHEN** system needs the active project
- **THEN** system reads `active_project` from config.json
- **THEN** if null or missing, commands that require a project print the appropriate error

#### Scenario: Write active project
- **WHEN** a project is created or switched to
- **THEN** system writes the project ID to config.json `active_project` field

### Requirement: Short UUID generation
The system SHALL generate 8-character UUID prefixes with type-specific prefixes for all entity IDs.

#### Scenario: ID format
- **WHEN** any entity is created
- **THEN** its ID follows the pattern `<prefix>_<8hex>` where prefix is one of: proj, feat, script, suite, env, run, srun, step
