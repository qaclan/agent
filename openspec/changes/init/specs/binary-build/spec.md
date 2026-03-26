## ADDED Requirements

### Requirement: Nuitka build script
The system SHALL include a `build.sh` script that compiles the CLI into a standalone single-file binary using Nuitka.

#### Scenario: Build produces binary
- **WHEN** user runs `bash build.sh`
- **THEN** Nuitka compiles `cli.py` with `--standalone --onefile`
- **THEN** output binary is placed at `dist/qaclan`
- **THEN** the binary is executable and handles all CLI commands

#### Scenario: Build script configuration
- **WHEN** examining build.sh
- **THEN** it uses `--output-filename=qaclan` and `--output-dir=dist`
