# 19 - Slack / Discord / Email Notifier

Deep-dive on feature #19 from [feature-ideas.md](../feature-ideas.md). Covers webhook integration, notification event taxonomy, and how this ties into the scheduler (feature #8).

---

## The problem

A test suite fails. Nobody knows.

Scheduled runs (feature #8) catch regressions automatically, but only if someone is watching QAClan's run history. Most users do not have the QAClan web UI open continuously. Notifications push results to where the team already is: Slack, Discord, or email.

## Example

```
15:30  Scheduled run: "regression-suite" starts
15:32  3 of 40 tests fail

Slack #qa-alerts:
┌────────────────────────────────────────────┐
│ ❌ QAClan: regression-suite FAILED         │
│ Project: my-app  Environment: staging      │
│ 3 failed / 40 total  •  Duration: 1m 47s  │
│                                            │
│ Failed tests:                              │
│  • login-flow       Locator not found      │
│  • checkout-guest   Network timeout        │
│  • password-reset   Unexpected redirect    │
│                                            │
│ View report: http://localhost:7823/runs/.. │
└────────────────────────────────────────────┘
```

Dev sees it within minutes. Fixes before users hit it.

## Impact

| Dimension | Effect |
|---|---|
| Reaction time | Hours → minutes. Failure at 3am gets fixed by 9am instead of being discovered by users. |
| Passive monitoring | Teams don't need to remember to check QAClan. Results come to them. |
| Scheduler value multiplier | Scheduled runs (feature #8) are much less useful without notifications. These two features unlock each other. |
| Adoption | Teams that get Slack notifications daily stay engaged. Silent tools get forgotten. |

Overall: **high impact when paired with scheduled runs.** Medium impact as a standalone feature (manual runs are already visible in the UI). Ship after feature #8.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **GitHub Actions** | Sends email on workflow failure. No Slack by default (needs Action plugin). | CI-only. Not from local QAClan runs. |
| **Datadog CI Visibility** | Rich notifications from CI pipelines. | Cloud, paid, complex setup. Requires Datadog agent. |
| **Mabl** | Native Slack/email/PagerDuty integration for test results. | Paid, cloud-hosted. |
| **Checkly** | Synthetic monitoring with Slack/PagerDuty alerts. | Cloud, paid. Not E2E test runner. |

**Our diff:** Notifications from local QAClan runs, no cloud required. Configured in QAClan UI, not in separate platforms. Integrates directly with suite runs and scheduled runs. Works from dev laptop.

## Notification channels

| Channel | Method | Difficulty |
|---|---|---|
| Slack | Incoming Webhook URL | Low — single HTTP POST |
| Discord | Incoming Webhook URL | Low — same pattern as Slack |
| Email | SMTP (configured in QAClan settings) | Medium — needs SMTP config |
| Microsoft Teams | Incoming Webhook | Low — same pattern |
| Custom webhook | HTTP POST with JSON body | Low — generic |

v1: Slack + Discord + Email. Teams + Custom webhook in v2.

## Notification events

| Event | When triggered | Default |
|---|---|---|
| `run_failed` | Any script in a suite run fails | Enabled |
| `run_passed` | Suite run completes with all passing | Disabled |
| `run_passed_on_retry` | Suite run "passed" but had retries | Optional |
| `flake_detected` | Script marked flaky (feature #6) | Optional |
| `schedule_missed` | Scheduled run skipped (QAClan wasn't running) | Optional |

Users pick which events trigger notifications per notification config.

## Schema

```sql
CREATE TABLE notification_configs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,       -- "QA Slack channel", "Email on failure"
    channel      TEXT NOT NULL,       -- slack | discord | email | webhook
    target       TEXT NOT NULL,       -- webhook URL or email address(es)
    events       TEXT NOT NULL,       -- JSON array: ["run_failed", "flake_detected"]
    enabled      INTEGER DEFAULT 1,
    created_at   TEXT NOT NULL
);
```

One row per notification target. A project can have multiple configs (e.g. Slack + email for failures, separate Slack for flakes).

## Slack / Discord message format

Slack Block Kit:
```json
{
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": "❌ regression-suite FAILED" }
    },
    {
      "type": "section",
      "fields": [
        {"type": "mrkdwn", "text": "*Project:*\nmy-app"},
        {"type": "mrkdwn", "text": "*Environment:*\nstaging"},
        {"type": "mrkdwn", "text": "*Result:*\n3 failed / 40 total"},
        {"type": "mrkdwn", "text": "*Duration:*\n1m 47s"}
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Failed tests:*\n• `login-flow` — Locator not found\n• `checkout-guest` — Network timeout"
      }
    },
    {
      "type": "actions",
      "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "View Report"}, "url": "http://localhost:7823/runs/abc123"}
      ]
    }
  ]
}
```

Discord uses a simpler embed format (same content, different JSON structure).

## Email format

Plain-text email with optional HTML version. Template:

```
Subject: [QAClan] regression-suite FAILED (3/40 tests)

Suite: regression-suite
Project: my-app
Environment: staging
Started: 2025-01-14 15:30:01
Duration: 1m 47s
Result: 3 FAILED / 40 total

Failed tests:
  • login-flow            Locator '#login-btn' not found
  • checkout-guest        network_idle timeout after 30s
  • password-reset        Expected /dashboard, got /error

View full report:
http://localhost:7823/runs/abc123
```

SMTP config in `~/.qaclan/config.json`:
```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "alerts@team.com",
  "smtp_password": "...",
  "smtp_from": "QAClan Alerts <alerts@team.com>"
}
```

Settings UI: SMTP form + "Send test email" button.

## Implementation path

### Phase 1 — Slack + Discord webhook

- Add `notification_configs` table.
- UI: "Notifications" tab in project settings. Add/edit/delete configs. "Test notification" button.
- Hook in run completion handler in [web/routes/runs.py](../../web/routes/runs.py): after `execute_run` finishes, call `send_notifications(suite_run)`.
- `send_notifications` reads enabled configs for the project, POSTs to each webhook.
- Non-blocking: fire notifications in a background thread. Failure silently logged.

### Phase 2 — email via SMTP

- SMTP config in settings UI + settings.json.
- Add email support to `send_notifications`.
- HTML + plaintext email body.

### Phase 3 — event filtering + flake integration

- Add event filtering: per-config, which events trigger this notification.
- Wire `flake_detected` event when feature #6 (Flaky Test Detection) lands.
- Wire `schedule_missed` when feature #8 (Scheduled Runs) lands.

## Open questions

- **"View report" link.** The link points to `http://localhost:7823/...` which only works from the developer's machine. If the team member clicks from their phone, it won't resolve. Solutions: (a) user configures a custom base URL in settings (for users who expose QAClan on a LAN IP), (b) link to cloud report if cloud sync is active (feature #20), (c) document the limitation. Start with (a) + (c).
- **Notification deduplication.** Scheduled suite runs every 30 minutes. Suite keeps failing for 4 hours. 8 identical Slack messages flood the channel. Add "only notify on first failure, then again when it passes" mode ("alert once").
- **Sensitive data in messages.** Error messages can contain URLs, values, selectors that reveal internal structure. Option to redact env var values in notifications.

## Next concrete step

Add `notification_configs` table migration. Build the Notifications tab UI (CRUD + test button). Implement `send_notifications` with Slack webhook POST. Hook into run completion in [web/routes/runs.py](../../web/routes/runs.py). Verify with a real Slack incoming webhook before shipping Phase 1.
