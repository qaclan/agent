## ADDED Requirements

### Requirement: Create an environment
The system SHALL create a named environment under the active project with a unique ID prefixed `env_`.

#### Scenario: Create environment successfully
- **WHEN** user runs `qaclan env create prod` with an active project
- **THEN** system creates an environment record linked to the active project
- **THEN** system prints `✓ Environment created: prod [env_<id>]`

#### Scenario: No active project
- **WHEN** user runs `qaclan env create prod` with no active project
- **THEN** system prints `No active project. Run: qaclan project create "name"`

### Requirement: Set environment variables
The system SHALL store key-value pairs for an environment. Secret values SHALL be stored but masked in output.

#### Scenario: Set a plain variable
- **WHEN** user runs `qaclan env set prod BASE_URL https://app.example.com`
- **THEN** system stores the key-value pair for the "prod" environment with `is_secret = 0`

#### Scenario: Set a secret variable
- **WHEN** user runs `qaclan env set prod PASSWORD secret123 --secret`
- **THEN** system stores the key-value pair with `is_secret = 1`

#### Scenario: Update an existing variable
- **WHEN** user runs `qaclan env set prod BASE_URL https://new.example.com` and BASE_URL already exists
- **THEN** system updates the existing value

### Requirement: List environments and variables
The system SHALL display environments and their variables, masking secret values as `********`.

#### Scenario: List all environments
- **WHEN** user runs `qaclan env list`
- **THEN** system displays all environments for the active project with their variables
- **THEN** secret values are shown as `********`

#### Scenario: List specific environment
- **WHEN** user runs `qaclan env list prod`
- **THEN** system displays only the "prod" environment and its variables

### Requirement: Delete an environment
The system SHALL delete an environment and its variables after user confirmation.

#### Scenario: Delete environment with confirmation
- **WHEN** user runs `qaclan env delete prod` and confirms
- **THEN** system deletes the environment and all its variables

#### Scenario: Environment not found
- **WHEN** user runs `qaclan env delete nonexistent`
- **THEN** system prints `Environment "nonexistent" not found. Run: qaclan env create nonexistent`
