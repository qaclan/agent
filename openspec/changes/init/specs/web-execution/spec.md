## ADDED Requirements

### Requirement: Execute a web suite
The system SHALL execute all scripts in a suite sequentially, injecting environment variables, tracking results per script, and recording the run.

#### Scenario: Run suite successfully (all pass)
- **WHEN** user runs `qaclan web run --suite suite_abc --env prod`
- **THEN** system loads suite items ordered by order_index
- **THEN** system validates suite channel is "web"
- **THEN** system loads environment variables for "prod"
- **THEN** system creates a suite_runs record with status RUNNING
- **THEN** for each script, system executes via `subprocess.run` with env vars injected
- **THEN** system prints live progress: `[1/3] Script name...  ✓ PASSED (Xs)`
- **THEN** system updates suite_runs with final status PASSED and counts
- **THEN** system updates suites table with last_run_at, last_run_status, and first_run_at if null

#### Scenario: Run suite with failures (continue on fail)
- **WHEN** a script exits with non-zero code during a run
- **THEN** system marks that script_run as FAILED with stderr as error_message
- **THEN** system continues executing remaining scripts
- **THEN** final suite_run status is FAILED
- **THEN** summary shows failed scripts with error messages

#### Scenario: Run suite with --stop-on-fail
- **WHEN** user runs with `--stop-on-fail` and a script fails
- **THEN** system marks remaining scripts as SKIPPED
- **THEN** system stops execution immediately

#### Scenario: Empty suite
- **WHEN** user runs a suite that has no scripts
- **THEN** system prints `Suite has no scripts. Add one: qaclan web suite add --suite <id> --script <id>`

#### Scenario: Environment not found
- **WHEN** user specifies an environment that does not exist
- **THEN** system prints `Environment "name" not found. Run: qaclan env create name`

#### Scenario: Run without --env
- **WHEN** user runs `qaclan web run --suite suite_abc` without `--env`
- **THEN** system executes scripts without additional environment variables

### Requirement: Run summary output
The system SHALL print a formatted summary after suite execution completes.

#### Scenario: Summary with failures
- **WHEN** a run completes with at least one failure
- **THEN** system prints separator, suite name, channel, status FAILED
- **THEN** system prints total, passed, failed, skipped counts and duration
- **THEN** system lists each failed script with its error message
- **THEN** system prints the run ID
