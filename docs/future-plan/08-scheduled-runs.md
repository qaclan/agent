# 08 - Scheduled Runs

Deep-dive on feature #8 from [feature-ideas.md](../feature-ideas.md). Covers scheduler architecture (thread vs system cron), notification coupling, and local-first design constraints.

---

## The problem

QAClan runs are always triggered manually: open UI, click Run. If the app breaks at 2am nobody knows until someone checks in the morning. Teams using QAClan as a local monitor need runs to happen automatically — without CI infrastructure.

## Example

```
Schedule: "smoke-suite" every 30 minutes
Notification: email on failure

Timeline:
03:00  run starts automatically  →  PASS  →  no notification
03:30  run starts automatically  →  PASS  →  no notification
04:00  run starts automatically  →  FAIL  →  email sent to qa@team.com
04:07  dev wakes up to: "smoke-suite FAILED. 2 of 20 tests broken. View: http://localhost:7823/runs/..."
04:15  dev fixes before standup
```

## Impact

| Dimension | Effect |
|---|---|
| Regression catch time | Hours → minutes. Scheduled run catches breaks during deploy window, not at first user complaint. |
| CI alternative | Teams without CI pipelines (agencies, small shops) get continuous monitoring from their dev machine. High impact for this segment. |
| Suite utilization | Suites become living monitors, not just "run before a release" tools. Raises perceived value of QAClan. |
| Local-first guarantee | No cloud dependency. Runs on the machine where QAClan is installed. |

Overall: **high impact**. One of the features that upgrades QAClan from "test runner" to "monitoring tool".

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **GitHub Actions cron** | `schedule: cron: '0 * * * *'` — runs tests in cloud CI. | Requires GitHub repo + Actions setup + cloud env configured. Overkill for local dev. |
| **Checkly** | Cloud synthetic monitoring with Playwright. Paid, cloud-only. | No local runs. Data leaves your machine. |
| **Datadog Synthetics** | Managed Playwright in cloud. Paid. | Same as Checkly. Expensive for small teams. |
| **cron + shell script** | `*/30 * * * * qaclan suite run smoke`. Works. | No UI. No notification integration. No result aggregation. User builds all of this. |

**Our diff:** Scheduler built into QAClan. Configure via UI (no crontab editing). Results land in the existing runs DB. Notification config is part of the same UI. Single tool covers scheduling + results + alerts. No external service.

## Architecture decision: background thread vs system cron

### Option A — background thread (Flask app must be running)

```python
# In web/__init__.py or qaclan.py serve command
from apscheduler import AsyncIOScheduler
scheduler = AsyncIOScheduler()
scheduler.start()

# On schedule create: scheduler.add_job(run_suite, CronTrigger.from_crontab(expr), id=schedule_id)
```

Pros:
- No system permissions. No crontab write.
- Portable (Linux/macOS/Windows same code).
- UI has live access to scheduler state ("next run at 14:30").

Cons:
- Runs stop if `qaclan serve` is not running.
- First-party scheduler dep (APScheduler ~4MB).

### Option B — write to system crontab (or Windows Task Scheduler)

```bash
# Generated crontab entry:
*/30 * * * * /usr/local/bin/qaclan suite run smoke --notify >> ~/.qaclan/scheduler.log 2>&1
```

Pros:
- Runs even without web UI open.
- Uses OS scheduler — battle tested.

Cons:
- Crontab manipulation is messy (parse, append, remove by ID).
- Windows Task Scheduler has completely different API.
- Cross-platform inconsistency.

### Decision

**Option A (background thread) for v1.** Simple, portable, no system permissions. Add a "Keep server running in background" mode later (could use `qaclan serve --background`). Document the dependency clearly: "Scheduled runs require `qaclan serve` to be running."

## Schema

```sql
CREATE TABLE schedules (
    id            TEXT PRIMARY KEY,
    suite_id      TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
    cron_expr     TEXT NOT NULL,     -- standard 5-field cron (min hr dom mon dow)
    enabled       INTEGER DEFAULT 1,
    notify_emails TEXT,              -- comma-separated, optional
    notify_webhook TEXT,             -- for feature #19 Slack/Discord hook
    last_run_at   TEXT,
    next_run_at   TEXT,              -- computed, for UI display
    last_status   TEXT,
    created_at    TEXT NOT NULL
);
```

## Cron expression UI

Don't make users type `*/30 * * * *`. Provide presets + a custom field:

| Preset label | Cron expression |
|---|---|
| Every 15 minutes | `*/15 * * * *` |
| Every 30 minutes | `*/30 * * * *` |
| Hourly | `0 * * * *` |
| Daily at 2am | `0 2 * * *` |
| Every weekday 9am | `0 9 * * 1-5` |
| Custom | (user types) |

Live preview: "Next run: Tuesday 14 Jan 2025 at 09:00" computed in real-time as user adjusts.

## Notification on failure

Phase 1: email via SMTP (user configures SMTP settings in QAClan settings).
Phase 2: webhook (integrates with feature #19 Slack/Discord).

Email template:
```
Subject: [QAClan] smoke-suite FAILED

Suite: smoke-suite
Time: 2025-01-14 02:30:01
Result: 3 failed / 20 total

Failed tests:
  - login-flow        error: locator '#login-btn' not found
  - checkout-guest    error: network request timed out

View full report: http://localhost:7823/runs/abc123
```

## Implementation path

### Phase 1 — CRUD + scheduler thread

- Add `schedules` table migration in [cli/db.py](../../cli/db.py).
- CRUD routes: `GET/POST /api/schedules`, `PUT/DELETE /api/schedules/:id`.
- Scheduler thread starts with `qaclan serve`. Loads enabled schedules from DB on boot. Uses APScheduler with SQLite job store so jobs survive restart.
- On trigger: calls existing `execute_run` function from [web/routes/runs.py](../../web/routes/runs.py) directly.
- UI: "Schedules" tab in suite detail page. Create/enable/disable/delete.

### Phase 2 — email notification

- SMTP config in `~/.qaclan/config.json` (smtp_host, port, user, password, from_addr).
- Settings UI: SMTP form with "Send test email" button.
- On schedule run complete: check `notify_emails`, send if any failure.

### Phase 3 — next-run preview + history

- Show "Next run: in 23 minutes" in schedule list.
- Schedule run history table on schedule detail page (last 20 runs, duration, status).

## Open questions

- **Missed runs.** If `qaclan serve` was down during a scheduled time, skip or catch up? Skip is simpler and safer (catching up could queue 10 runs at once). Log the miss.
- **Concurrency.** What if a scheduled run starts while a manual run is already in progress for the same suite? Options: queue, skip, or run both. Skip for v1 with a log notice.
- **Time zone.** APScheduler runs in system time zone by default. Cron expressions should be explicit. UI shows system time zone next to cron preview.

## Next concrete step

Add `schedules` table migration to [cli/db.py](../../cli/db.py). Add `pip install apscheduler` to requirements. Wire scheduler thread start into the `serve` command in [qaclan.py](../../qaclan.py). Implement CRUD routes. No notifications in Phase 1.
