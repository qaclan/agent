## ADDED Requirements

### Requirement: API command group exists with coming soon stubs
The system SHALL register the `qaclan api` command group with subcommands that all print a "coming soon" message.

#### Scenario: API feature create
- **WHEN** user runs `qaclan api feature create "Auth Endpoints"`
- **THEN** system prints `⚠ API testing is coming soon.`

#### Scenario: API suite create
- **WHEN** user runs `qaclan api suite create "API Smoke"`
- **THEN** system prints `⚠ API testing is coming soon.`

#### Scenario: API run
- **WHEN** user runs `qaclan api run --suite suite_abc --env prod`
- **THEN** system prints `⚠ API testing is coming soon.`

#### Scenario: API command group is visible in help
- **WHEN** user runs `qaclan api --help`
- **THEN** system shows the api group with available subcommands
