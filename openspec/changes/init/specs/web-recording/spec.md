## ADDED Requirements

### Requirement: Record a web script via Playwright codegen
The system SHALL launch Playwright codegen, capture the generated script, and save it as a named script under a feature.

#### Scenario: Record script successfully
- **WHEN** user runs `qaclan web record --feature feat_abc123 --name "Verify successful login"`
- **THEN** system validates the feature exists and has `channel = web`
- **THEN** system prints recording context (script name, feature name, channel)
- **THEN** system launches `playwright codegen --output <tmp_path> --target python`
- **THEN** after browser closes, system reads the generated script
- **THEN** system copies script to `~/.qaclan/scripts/<script_id>.py`
- **THEN** system creates a script record with `source = CLI_RECORDED`
- **THEN** system prints confirmation with script ID, feature name, and file path

#### Scenario: Record with start URL
- **WHEN** user runs `qaclan web record --feature feat_abc123 --name "Test" --url https://app.example.com`
- **THEN** system appends the URL to the Playwright codegen command

#### Scenario: Empty recording
- **WHEN** user closes the browser without interacting
- **THEN** system prints `Nothing was recorded. Close the browser only after interacting with the app.`

#### Scenario: Playwright not installed
- **WHEN** Playwright is not available on the system
- **THEN** system prints `Playwright not found. Run: pip install playwright && playwright install chromium`

#### Scenario: Feature not found
- **WHEN** user provides a feature ID that does not exist
- **THEN** system prints `Feature feat_<id> not found. Run: qaclan web feature list`
