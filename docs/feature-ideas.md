# Feature Ideas - Detailed Plans

Each idea has: what it does, example, impact, why better than raw Playwright, who else does it.

---

## 1. Smart Selector Healing

### What it does
When a selector breaks (page changed `#login-btn` to `#login-btn-v2`), the test does not fail right away. Instead it tries other ways to find the element: text content, button role + name, nearby `data-testid`, ARIA label. If it finds a match, it runs the action and suggests a fix to update the script.

### Plan
- Add a wrapper around Playwright locator calls in the script harness.
- On `TimeoutError`, capture the DOM and the intended action.
- Run fallback strategies in order. Pick the best match using score (text similarity + position).
- Store every heal in a `selector_heals` table.
- UI shows: "This selector was healed 3 times. Want to update?"
- One-click button rewrites the script file with the new selector.

### Example
```python
# User wrote this
await page.locator("#submit-btn").click()

# Page changed. ID is now "submit-button-primary".
# Without healing: test fails.
# With healing: finds the button by text "Submit", clicks it, logs the heal.
# UI shows suggestion to replace "#submit-btn" with getByRole("button", {name: "Submit"}).
```

### Impact
- Fewer false failures from small UI changes.
- Less time spent fixing tests after every release.
- Self-improving test suite over time.

### vs Plain Playwright
Playwright has good locators (`getByRole`, `getByText`) but if you wrote the test with a bad selector, it just fails. No retry with other strategies. No suggestion to fix. User has to debug, find the new selector, edit the file, commit.

### Already done by
- **Testim** (paid) - "Smart Locators" using AI.
- **Mabl** (paid) - auto-heal selectors.
- **Functionize** (paid) - ML-based healing.
- **Playwright itself**: no native healing.

---

## 2. Visual Element Picker

### What it does
User opens a live browser from the web UI. Clicks any element on the page. The picker returns the best selector and inserts it into the script at the cursor position.

### Plan
- Add "Pick Element" button next to script editor.
- Launches Playwright browser with an injected overlay script.
- Overlay highlights element on hover.
- On click, runs selector generation (same logic Playwright codegen uses).
- Posts selector back to web UI via WebSocket.
- Inserts code snippet at cursor: `await page.getByRole("button", {name: "Login"}).click()`.

### Example
User writing a script. Needs to click the "Forgot Password" link. Instead of opening DevTools, copying the selector, guessing the best locator type, the user clicks "Pick Element", clicks the link in the live browser, and the code is inserted automatically.

### Impact
- Big speed boost during script authoring.
- New users do not need to learn Playwright locator API.
- Less switching between IDE, browser, and DevTools.

### vs Plain Playwright
Playwright has `codegen` but it records a full session from start. Cannot pick one element mid-script. Cannot insert into an existing script. Cannot use it while editing.

### Already done by
- **Playwright Inspector** - pick mode exists but only inside codegen flow.
- **Cypress Studio** - similar visual recorder.
- **Selenium IDE** - point-and-click record.
- No tool has "pick one element and inject into existing script" as a clean flow.

---

## 3. Recorded Action Editor (Timeline View)

### What it does
After recording with codegen, show the steps in a visual timeline. Each step is a card: action type, target, value, screenshot. User can drag to reorder, delete, edit values, add waits between steps. No need to touch raw code.

### Plan
- Parse the codegen script output into a list of actions (`{action, selector, value, line}`).
- Render as cards in the UI with thumbnails (from a re-run capture).
- Drag-and-drop reorder, inline edit.
- On save, regenerate the script file from the action list.
- Keep raw code view as a tab for advanced users.

### Example
Recorded a 20-step login flow. Step 7 is a wrong click. Currently: open file, find line 14, delete it, save. With timeline: click delete on card 7. Done.

### Impact
- Non-coders can fix recorded tests.
- Faster cleanup of long recordings.
- Better mental model of the test flow.

### vs Plain Playwright
Playwright codegen outputs raw code only. No visual editor. Any edit is text edit.

### Already done by
- **Selenium IDE** - has a step table editor.
- **Katalon Recorder** - timeline view.
- **Cypress** - no built-in timeline.
- **Mabl/Testim** - timeline-style step editors (paid).

---

## 4. Snippet Library

### What it does
Reusable code blocks for common flows: login, signup, fill checkout form, accept cookies. User saves a block once, inserts into any script with one click. Per-project and global snippets.

### Plan
- New table: `snippets` (id, name, language, code, scope=project|global, tags).
- UI: snippet panel in script editor with search.
- Click snippet to insert at cursor.
- Snippets can have parameters: `{{email}}`, `{{password}}` - prompt user on insert.
- Sync to cloud (optional) for team sharing.

### Example
```python
# Snippet: "login_as_admin"
async def login_as_admin(page):
    await page.goto("/login")
    await page.fill("#email", "{{email}}")
    await page.fill("#password", "{{password}}")
    await page.click("text=Sign In")
    await page.wait_for_url("/dashboard")

# In any script:
# Click snippet "login_as_admin" -> inserts the call + import.
```

### Impact
- DRY tests. Update login once, all tests get it.
- Faster authoring.
- Team can share known-good patterns.

### vs Plain Playwright
Playwright has page objects and fixtures but you build them by hand. No catalog. No sharing across projects without copy-paste.

### Already done by
- **Postman** - request snippets, collections.
- **VS Code snippets** - generic, not test-aware.
- **Cypress Cloud** - shared commands per org.
- **Mabl** - shared steps across tests.

---

## 5. Natural Language to Step

### What it does
User types: "click the login button, then fill email with test@example.com". Tool converts to Playwright code. Uses an LLM (BYOK or local model).

### Plan
- Add a chat box next to script editor.
- User types instructions in plain English.
- Send to LLM with context: current DOM (if browser open), current script, available locators.
- LLM returns Playwright code.
- Insert at cursor with a confirm button.
- Cache common patterns to reduce LLM calls.

### Example
```
User types: "Wait for the modal to appear, then close it"

Generated:
await page.wait_for_selector(".modal", state="visible")
await page.locator(".modal .close-btn").click()
```

### Impact
- Lowest barrier to entry. Anyone can write tests.
- Speed up authoring for experienced users too.
- Combine with element picker: "click that thing I just picked".

### vs Plain Playwright
Playwright has no LLM features. Users write code by hand or record then edit.

### Already done by
- **Promptest, BrowserCat, Skyvern** - early AI test tools.
- **Mabl AI** - natural language tests (paid).
- **Reflect.run** - no-code AI tests.
- **GitHub Copilot** - works with Playwright but generic, no test context.

---

## 6. Flaky Test Detection

### What it does
Track pass/fail history per script. If a test passes sometimes and fails sometimes on the same code, mark it flaky. Show flake rate in dashboard. Suggest fixes (add wait, use auto-wait, fix race condition).

### Plan
- Use existing `runs` table data.
- Compute pass rate per script over the last N runs.
- Flag scripts with pass rate between 5% and 95% as flaky.
- Show a "Flaky" badge in the script list.
- On script detail page, show timeline of pass/fail with hover-over failure reasons.
- Detect patterns: "fails 80% of the time on step 5" - suggest adding `wait_for`.

### Example
Script "checkout-flow" ran 50 times. Passed 42, failed 8. All failures on "click confirm button". UI shows: "Flaky on step 9. Try adding `wait_for_load_state('networkidle')` before the click."

### Impact
- Catch flakes before they erode trust in the suite.
- Stop wasting time re-running flaky tests.
- Data-driven decisions about what to fix first.

### vs Plain Playwright
Playwright has `--retries` flag but does not track flake rate. No flake dashboard. No suggestions.

### Already done by
- **CircleCI Test Insights** - flake detection.
- **Datadog CI Visibility** - flake tracking.
- **BuildPulse** - dedicated flaky test tool.
- **Playwright Cloud (Currents)** - flake reports (paid).

---

## 7. Parallel Run Groups

### What it does
Run multiple scripts at the same time. Two modes: isolated (each script has its own state) or shared (scripts share login/state). Speed up suite runs.

### Plan
- New UI: "Run Group" - select N scripts.
- Choose mode: parallel-isolated, parallel-shared, sequential.
- Spawn N subprocesses with separate run dirs (already structured this way).
- Aggregate results to a single group report.
- Track resource usage. Cap concurrency based on CPU/RAM.

### Example
Suite has 30 tests, 2 minutes each. Sequential: 60 minutes. Parallel with 6 workers: 10 minutes.

### Impact
- 5-10x faster suite runs.
- Better CPU usage on dev machines.
- Encourages bigger suites.

### vs Plain Playwright
Playwright Test runner has parallel workers built in. But QAClan currently runs one subprocess per script. Adding this gives parity. Plus QAClan adds the state-sharing mode which Playwright does not have (workers are always isolated).

### Already done by
- **Playwright Test** - native parallel workers.
- **Cypress** - parallel via Cypress Cloud (paid).
- **TestCafe** - concurrency flag.
- **Mocha/Jest** - parallel test runners.

---

## 8. Scheduled Runs

### What it does
Cron-style scheduler. "Run smoke suite every hour. Run full suite at 2am. Email me on failure."

### Plan
- New table: `schedules` (id, suite_id, cron_expr, notify_emails, last_run, next_run).
- Background scheduler thread when web server is running.
- Or system-level: write to user crontab on schedule create.
- UI: pick suite, pick cron pattern (with presets: hourly, daily, weekly).
- On run complete: send notification if any test failed.

### Example
Schedule "smoke-suite" every 30 minutes. Test breaks at 3am. Email alert. Team sees it before users do.

### Impact
- Catch regressions without manual runs.
- Acts as continuous monitoring.
- Local-first option for teams that cannot use cloud CI.

### vs Plain Playwright
Playwright has no scheduler. User builds one with cron + shell scripts.

### Already done by
- **GitHub Actions cron** - scheduled workflows.
- **Checkly** - synthetic monitoring with Playwright (paid).
- **Datadog Synthetics** (paid).
- **Mabl** - schedule plans (paid).

---

## 9. Run on File Change (Watch Mode)

### What it does
Watch script files. When a file changes, re-run that script. Like `jest --watch` but for E2E tests.

### Plan
- Use `watchdog` (Python) to watch `~/.qaclan/scripts/`.
- On change, debounce 500ms, then run the changed script.
- UI shows "watching" badge with live status.
- Optionally: also re-run dependent scripts (shared state).

### Example
User edits a login script. Save. Test runs automatically in background. Sees pass/fail in 10 seconds without leaving the editor.

### Impact
- Tight feedback loop while authoring.
- Faster iteration.

### vs Plain Playwright
Playwright Test has `--watch` mode. QAClan does not currently. This brings parity.

### Already done by
- **Playwright Test** - native watch.
- **Jest, Vitest, Cypress** - all have watch.
- Standard expectation now.

---

## 10. Retry Policy

### What it does
Per-script setting: "retry up to 3 times on failure with 5 second backoff". Mark "passed on retry" separately from "passed first try" so you can spot flakes.

### Plan
- Add `retry_count` and `retry_delay` columns to `scripts` table.
- In runner, on failure: wait, retry, count attempts.
- Store each attempt as a sub-run.
- Run status: `passed`, `passed_on_retry`, `failed`.
- UI shows retry icon next to passed-on-retry runs.

### Example
Login test fails once due to slow backend. Retries. Passes. Marked as "passed on retry" - test still works but flagged for investigation.

### Impact
- Reduce noise from one-off flakes.
- Still track real reliability via the "passed on retry" count.

### vs Plain Playwright
Playwright has `test.describe.configure({retries: 2})`. Works but per-file, not per-test in a simple UI. QAClan adds per-script UI control and the "passed on retry" distinction.

### Already done by
- **Playwright Test** - retries flag.
- **Cypress** - retries config.
- **Mocha** - this.retries().

---

## 11. Trace Viewer Integration

### What it does
Embed Playwright's trace viewer in the QAClan web UI. After a failed run, click "View Trace" - get the full timeline, DOM snapshots, network log, console log, screenshots inline.

### Plan
- Already capturing `trace.zip` per run (if enabled).
- Bundle `playwright show-trace` server or use the web-based viewer at `trace.playwright.dev`.
- Host trace files via Flask route.
- Iframe the trace viewer into the run detail page.

### Example
Test fails. Click "View Trace". See exactly what the page looked like at each step. Click step 5, see DOM, network calls, what locator was used.

### Impact
- Root-cause failures fast.
- No need to re-run with debug flags.

### vs Plain Playwright
Playwright provides the trace viewer. QAClan just needs to surface it well. Currently user has to find the file and open it manually.

### Already done by
- **Playwright Test** - trace viewer in HTML reporter.
- **Currents.dev** (paid) - hosts traces.

---

## 12. Diff Between Runs

### What it does
Pick two runs of the same script. Show what changed: screenshot diff, DOM diff, timing diff, network call diff.

### Plan
- Store screenshots, DOM snapshots, network logs per run (more storage but valuable).
- UI: "Compare with previous run" button.
- Use image diff library (`pixelmatch` or Pillow) for screenshot diff.
- Use HTML diff for DOM.
- Show side-by-side.

### Example
Test passed yesterday, failed today. Diff shows: a button moved 20px, breaking the click coordinate. Or: a new modal appeared that blocks the flow.

### Impact
- Spot real UI regressions instantly.
- Useful for visual regression testing.
- Helps debug "why is it failing now when it passed yesterday".

### vs Plain Playwright
Playwright has `toHaveScreenshot()` for visual regression but it is opt-in per assertion. No run-to-run diff out of the box.

### Already done by
- **Percy** (BrowserStack) - visual diff.
- **Chromatic** - storybook visual diff.
- **Applitools** - visual AI testing.
- **Playwright** - has `expect(page).toHaveScreenshot()`.

---

## 13. Step-by-Step Replay

### What it does
Run a script in "debug mode": pause after each step. Inspect state, DOM, network. Resume or skip.

### Plan
- Special run mode: inject pause between actions in the harness.
- WebSocket between subprocess and UI.
- UI shows "Paused at step 5" with resume/skip/abort buttons.
- Inspect `state.json` and current page snapshot during pause.

### Example
Test fails at step 12. User runs in debug mode. Steps through. Sees state.json has stale cookie. Now knows the fix.

### Impact
- Debug without writing print statements.
- Inspect state mid-run.

### vs Plain Playwright
Playwright has `PWDEBUG=1` which opens Inspector and pauses on each line. QAClan would integrate this into the web UI instead of a separate window.

### Already done by
- **Playwright Inspector** - has step/pause.
- **Cypress Test Runner** - time-travel debugger.

---

## 14. Env Var Profiles

### What it does
Store named env var sets: "staging", "prod", "local". Switch with one click. Injected into runs.

### Plan
- Already partly there (`env` table). Add profile concept.
- Profile = named bundle of env vars.
- UI: drop-down on run page: "Run with profile [staging]".
- Profile applies on subprocess env.
- Secrets in profile encrypted at rest.

### Example
Same test "login flow" runs on `staging.app.com` with test users, then on `prod.app.com` with smoke-only users. One script, two profiles, no script changes.

### Impact
- One test suite, many environments.
- No hardcoded URLs.
- Safer secrets handling.

### vs Plain Playwright
Playwright uses `process.env` and `.env` files. Switching means re-exporting vars or running with different `.env` files. No UI.

### Already done by
- **Postman** - environments.
- **Cypress** - env configs per file.
- **GitHub Actions** - env per workflow.

---

## 15. Fixture / Data Factories

### What it does
Generate test data on demand: fake users, orders, addresses. Cleanup after run.

### Plan
- Library of factory functions: `make_user()`, `make_order()`.
- Hook into setup/teardown of script.
- Use Faker or built-in random generators.
- Track created data in DB. Cleanup pass deletes by ID after run.
- Optional: API integration to create real records via backend.

### Example
```python
user = await factory.user(role="admin")  # makes a real user
await page.goto("/login")
await page.fill("#email", user.email)
# ... test ...
# Cleanup runs automatically: delete the user.
```

### Impact
- No more hardcoded test users that drift.
- Each run is isolated.
- Safer for shared test envs.

### vs Plain Playwright
Playwright has fixtures (`test.extend`) but no data factory library. User builds it themselves.

### Already done by
- **Ruby on Rails / FactoryBot** - well-known pattern.
- **factory_boy** (Python).
- **Cypress** - has fixtures but as static JSON.
- **Playwright** - manual via test.extend.

---

## 16. Secrets Vault

### What it does
Store credentials encrypted in the local DB. Inject into runs as env vars. Never appear in script files.

### Plan
- New table: `secrets` (name, encrypted_value, project_id).
- Use `cryptography` lib with key derived from machine ID + user passphrase.
- UI: add/edit/delete secret. Cannot view value after save (write-only).
- In script: `os.environ["QACLAN_SECRET_LOGIN_PASS"]`.
- Optional cloud sync: never sync secrets unless user opts in (zero-knowledge encrypted).

### Example
User stores `admin_password` in vault. Script uses `os.environ["QACLAN_SECRET_admin_password"]`. Password never in git, never in DB plaintext, never in run logs.

### Impact
- Safer credential handling.
- Pass compliance checks.
- Share scripts without leaking creds.

### vs Plain Playwright
Playwright has nothing for secrets. User puts them in `.env` (often committed by mistake) or hard-codes them.

### Already done by
- **HashiCorp Vault** - full secrets manager.
- **Doppler** - dev-focused secret store.
- **GitHub Actions secrets**.
- **1Password CLI integration** in some test tools.

---

## 17. GitHub Actions Generator

### What it does
Click a button. Get a `.github/workflows/qaclan.yml` file ready to run your QAClan suite in CI.

### Plan
- Template the workflow file.
- Fill in: suite name, env profile, browsers, OS matrix.
- Output to clipboard or download.
- Optionally PR the file to user's repo via GitHub API.

### Example
```yaml
# Generated workflow
name: QAClan Tests
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: curl -sSL https://qaclan.com/install.sh | bash
      - run: qaclan setup
      - run: qaclan suite run smoke --reporter junit
```

### Impact
- Zero-effort CI integration.
- New users productive in CI in 1 minute.

### vs Plain Playwright
Playwright provides a CI doc page. User reads, copies, edits. QAClan auto-generates with their suite, env, browsers pre-filled.

### Already done by
- **Cypress** - `cypress init` scaffolds CI configs.
- **Playwright** - `npm init playwright` asks "add GitHub Actions?".

---

## 18. JUnit / Allure Export

### What it does
Export run results in JUnit XML or Allure format. Consumed by Jenkins, CircleCI, GitLab, Bamboo, etc.

### Plan
- Reporter plugin: takes run data, writes XML/JSON in standard format.
- CLI flag: `qaclan suite run --reporter junit --output report.xml`.
- Map QAClan run states to JUnit fields.
- Embed screenshots/traces as attachments where supported.

### Impact
- Drop-in to any CI system.
- Engineering teams expect this format.

### vs Plain Playwright
Playwright Test has JUnit and Allure reporters built in. QAClan needs them to be CI-compatible.

### Already done by
- **Playwright Test** - junit, json, html, allure reporters.
- **Most test runners** support this.

---

## 19. Slack / Discord / Email Notifier

### What it does
Send run results to a channel. Configurable per suite. Templates: "5 of 50 tests failed - see report".

### Plan
- New table: `notifications` (channel, webhook_url, events, template).
- Hooks: `on_run_complete`, `on_run_failed`, `on_flake_detected`.
- POST to webhook URL with formatted message.
- Support Slack blocks, Discord embeds, plain email via SMTP or API.

### Example
Smoke suite fails at 3am. Slack channel #qa-alerts gets a message: "Smoke suite FAILED. 3 of 20 tests broken. View report: link".

### Impact
- Faster reaction to failures.
- No need to babysit runs.

### vs Plain Playwright
Playwright has no notification system. User pipes output to a shell script or builds a custom reporter.

### Already done by
- **Datadog CI**, **Mabl**, **Checkly** - native notifications.
- **GitHub Actions** - via action plugins.
- **Sentry** - error notifications.

---

## 20. Public Share Link

### What it does
Generate a read-only URL for a run report. Anyone with the link can see the report. No login.

### Plan
- Cloud sync uploads the run report.
- Generate a UUID token. URL: `qaclan.com/r/<token>`.
- Token revocable. Optional expiry.
- View shows: pass/fail, steps, screenshots, traces. No edit.

### Example
QA finds a bug. Shares link with dev. Dev sees the exact failure trace without installing QAClan.

### Impact
- Better bug reports.
- Faster triage with non-QA team members.
- Marketing benefit - links spread the product.

### vs Plain Playwright
Playwright report is a static folder. User has to host it themselves or zip and email.

### Already done by
- **CodeSandbox, StackBlitz** - share links.
- **Currents.dev** - shareable Playwright reports (paid).
- **Cypress Cloud** - dashboard sharing (paid).

---

## 21. Suite / Tag System

### What it does
Group scripts with tags: `@smoke`, `@regression`, `@checkout`. Run all scripts with a tag. Run multiple tags. Exclude tags.

### Plan
- Add `tags` column (comma-separated or many-to-many table).
- CLI: `qaclan run --tags smoke,checkout --exclude slow`.
- UI: filter by tag. "Run all smoke tests" button.
- Tag suggestions from existing usage.

### Example
30 scripts. Tag 5 as `@smoke`. Tag 20 as `@regression`. Tag 5 as `@nightly`. Different schedules run different sets.

### Impact
- Same suite, many run profiles.
- No duplicate scripts for "fast" vs "full" runs.

### vs Plain Playwright
Playwright has `test.describe.skip`, `@tag` annotations, and `--grep` for filtering. Works but command-line only. QAClan adds visual filtering and per-tag schedules.

### Already done by
- **Playwright Test** - tags via grep.
- **Cypress** - via grep or plugins.
- **Cucumber** - tags are core feature.

---

## 22. Comments on Runs

### What it does
Team members leave comments on specific runs or specific failed steps. @mention to notify.

### Plan
- New table: `run_comments` (run_id, step_index, author, text, created_at).
- UI: comment thread on run detail page.
- Email or Slack notification on @mention.
- Cloud sync for team visibility.

### Example
QA marks a flaky run with "ignore - known issue ABC-123". Dev sees comment, links to Jira ticket. History preserved.

### Impact
- Async triage.
- Knowledge captured next to the data.

### vs Plain Playwright
Playwright has nothing for comments.

### Already done by
- **Cypress Cloud** - run comments.
- **Mabl** - comment on results.
- **GitHub PR reviews** - similar pattern.

---

## 23. Run Approval Gates (GitHub Check)

### What it does
Make a PR block until QAClan suite passes. Integrate as a GitHub Check.

### Plan
- GitHub App or Action that calls QAClan suite via cloud.
- Post check status to PR.
- "Pending" while running. "Pass" or "Fail" after.
- Link to full report.

### Example
PR opened. QAClan runs smoke suite. Suite fails. PR shows red X. Merge blocked.

### Impact
- Stop bad code from merging.
- Tests become a gate, not a suggestion.

### vs Plain Playwright
Playwright via GitHub Actions can do this manually. QAClan would make it one-click setup with the cloud already coordinating.

### Already done by
- **Vercel Preview Checks**.
- **Mabl PR checks**.
- **Cypress Cloud GitHub integration**.
- **Codecov, SonarCloud** - similar gate pattern.

---

## 24. Local AI Assistant Tab

### What it does
Chat tab in the UI. Ask "why did this fail" or "fix this test". AI reads the trace, the script, and the DOM. Suggests fix or explains.

### Plan
- BYOK: user enters OpenAI / Anthropic / local Ollama key.
- Build context: failed step, trace summary, last passing version of the script, recent code changes.
- Send to LLM with tool calls (read more context, propose edit).
- Show suggested fix as a diff. User accepts or rejects.

### Example
```
User: "Why did checkout fail?"
AI: "Step 9 timed out clicking #pay-button. DOM shows the button is hidden 
     behind a modal that appeared in step 7. Try adding 
     `await page.locator('.modal-close').click()` after step 7."
     [Apply Fix] [Show Diff]
```

### Impact
- Debugging gets 10x faster.
- New users get unstuck without asking teammates.
- Big marketing hook.

### vs Plain Playwright
Playwright has no AI features. Users use external Copilot/ChatGPT and paste manually.

### Already done by
- **Cursor IDE** - AI-aware code edits.
- **Reflect.run, Promptest** - early AI test debuggers.
- **CodiumAI** - test-focused AI.

---

## 25. Coverage View

### What it does
Track which URLs, API endpoints, or UI routes are touched by your tests. Show gaps.

### Plan
- During run, capture all `page.goto`, `page.url`, and network requests.
- Store as `run_coverage` table.
- UI: tree view of site URLs. Color: green (tested), yellow (partial), red (untested).
- Optional: scrape sitemap or read route file to know what exists.

### Example
Dashboard shows: 47 of 80 URLs are covered. `/admin/billing/*` is fully untested. `/settings/security` has partial coverage.

### Impact
- See QA blind spots.
- Prioritize new tests by coverage.
- Justify QA investment with data.

### vs Plain Playwright
Playwright has `--coverage` for JS code coverage, not URL/route coverage. Different concept.

### Already done by
- **Postman** - API coverage.
- **CodeCov, Coveralls** - code coverage (different).
- Uncommon as a feature for E2E URL coverage.

---

## 26. Mobile / Responsive Presets

### What it does
One script, run across many viewport sizes: iPhone, iPad, desktop, big-screen. See which break.

### Plan
- New concept: "Device Profile" (name, width, height, user-agent, touch).
- Run script with each profile in a matrix.
- Result grid: script x profile = pass/fail/screenshot.
- Built-in presets matching Playwright's `devices` registry.

### Example
"Login flow" tested on iPhone 12, iPad, Desktop 1080p, Desktop 4K. Fails on iPhone 12 - mobile menu hides the login link.

### Impact
- Catch responsive bugs.
- One test, many devices, no duplication.

### vs Plain Playwright
Playwright has `devices['iPhone 12']` and project configs for matrix. Works but config-heavy. QAClan adds the matrix view and report.

### Already done by
- **BrowserStack, Sauce Labs** - device cloud (paid).
- **Playwright projects config** - matrix support.
- **Cypress** - viewport per test.

---

