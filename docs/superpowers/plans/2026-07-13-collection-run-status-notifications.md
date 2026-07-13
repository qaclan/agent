# Collection Run Status Chip + Completion Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a top-bar chip that lets a user jump back to a running API-collection run from anywhere in the API section, plus a sticky/OS notification when a run finishes unattended.

**Architecture:** One shared poller (`active-runs-tracker.js`) replaces the sidebar's existing self-poll of `GET /api-collection-runs?status=RUNNING`. It feeds three independent consumers: the sidebar's running-dots (existing, refactored to consume instead of poll), a new top-bar chip (`run-status-chip.js`), and a new completion notifier (`run-notification.js`) that shows a sticky banner and, if permitted, a native OS notification. All wiring lives in `api-section.js`.

**Tech Stack:** Vanilla JS ES modules (no build step, no bundler, no test framework), served as native browser modules (`<script type="module">`). Backend: existing Flask endpoints, unchanged — `GET /api/api-collection-runs?status=RUNNING` and `GET /api/api-collection-runs/<id>` already return every field needed (`id`, `collection_id`, `collection_name`, `status`, `total`, `passed`, `failed`, `error_count`).

## Global Constraints

- No automated test framework or linter is configured in this repo (per CLAUDE.md). Verification steps below use `node --check <file>` for syntax validation and manual browser exercise for behavior — do not introduce a test runner as part of this work.
- No backend changes are needed or in scope — the existing `api_collection_runs` endpoints already return every field this feature uses.
- Follow existing code conventions in `web/static/api/`: inline `style.cssText` (no separate CSS files), `_esc()` helper for HTML-escaping interpolated text, `window.api(method, path, body)` for all backend calls, CSS custom properties from `web/static/style.css` only (never invent a variable name that isn't defined there).
- Scope is frontend-only, single feature; do not split into further sub-plans.

---

### Task 1: Active runs tracker service

**Files:**
- Create: `web/static/api/services/active-runs-tracker.js`

**Interfaces:**
- Consumes: global `window.api(method, path, body)` (already defined in `web/static/api/api-section.js:6-18`, available by the time this module is used).
- Produces: `startActiveRunsTracker({ onChange, onCompleted }) -> { stop() }`. `onChange(runs)` fires every poll tick with the current RUNNING-status run array (each item has `id`, `collection_id`, `collection_name`, `status`, `total`, `passed`, `failed`, `error_count`, `started_at`). `onCompleted(run)` fires once per run the moment it drops out of the RUNNING list, with the full run object from `GET /api-collection-runs/<id>` (same shape plus `finished_at`, `request_results`).

- [ ] **Step 1: Create the tracker module**

```js
/**
 * startActiveRunsTracker({ onChange, onCompleted }) -> { stop }
 * Single shared poller for GET /api-collection-runs?status=RUNNING (every 3s).
 * onChange(runs): fires every tick with the current RUNNING list.
 * onCompleted(run): fires once, when a previously-seen run drops out of the
 * RUNNING list — fetches its final state once via GET /api-collection-runs/<id>.
 */
export function startActiveRunsTracker({ onChange, onCompleted }) {
  let _prevIds = new Set();
  let _stopped = false;
  let _timer = null;

  async function _fetchCompleted(runId) {
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (res.ok && res.run && onCompleted) onCompleted(res.run);
    } catch (_) {}
  }

  async function _tick() {
    if (_stopped) return;
    try {
      const res = await window.api('GET', '/api-collection-runs?status=RUNNING');
      const runs = res.runs || [];
      const curIds = new Set(runs.map(r => r.id));

      for (const id of _prevIds) {
        if (!curIds.has(id)) _fetchCompleted(id);
      }
      _prevIds = curIds;

      if (onChange) onChange(runs);
    } catch (_) {}
  }

  _tick();
  _timer = setInterval(_tick, 3000);

  return {
    stop() {
      _stopped = true;
      if (_timer) { clearInterval(_timer); _timer = null; }
    },
  };
}
```

- [ ] **Step 2: Syntax-check the file**

Run: `node --check web/static/api/services/active-runs-tracker.js`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/services/active-runs-tracker.js
git commit -m "feat(api): add shared active-runs poller for collection runs"
```

---

### Task 2: Top-bar run-status chip component

**Files:**
- Create: `web/static/api/components/run-status-chip.js`

**Interfaces:**
- Consumes: nothing beyond the DOM `container` and callbacks passed at mount time. No dependency on Task 1's module — it only receives already-fetched run arrays via `update()`.
- Produces: `mountRunStatusChip(container, { getCurrentViewedRunId, onJump }) -> { update(runs), refresh() }`. `update(runs)` stores the run list and re-renders. `refresh()` re-renders using the last-provided run list (used right after navigation, so the chip updates instantly instead of waiting for the next poll tick). `onJump(runId, collectionId, collectionName)` is called on click/row-click.

- [ ] **Step 1: Create the chip module**

```js
/**
 * mountRunStatusChip(container, { getCurrentViewedRunId, onJump }) -> { update, refresh }
 * Renders a pill in `container` for any RUNNING collection run other than
 * the one the user is currently viewing (getCurrentViewedRunId()). Hidden
 * when there's nothing to show. Click jumps to the run via onJump.
 */
export function mountRunStatusChip(container, { getCurrentViewedRunId, onJump }) {
  let _runs = [];
  let _dropdownOpen = false;

  const chip = document.createElement('div');
  chip.id = 'run-status-chip';
  chip.style.cssText = 'position:relative;display:none;align-items:center;gap:6px;' +
    'padding:4px 10px;border-radius:14px;background:var(--warning-bg);' +
    'border:1px solid var(--warning);font-size:11px;font-weight:600;' +
    'color:var(--warning);cursor:pointer;white-space:nowrap;user-select:none;';
  container.appendChild(chip);

  const label = document.createElement('span');
  chip.appendChild(label);

  const dropdown = document.createElement('div');
  dropdown.style.cssText = 'position:absolute;top:calc(100% + 4px);right:0;' +
    'background:var(--bg-elevated);border:1px solid var(--border-strong);' +
    'border-radius:8px;box-shadow:var(--shadow-md);min-width:220px;display:none;' +
    'z-index:50;overflow:hidden;';
  chip.appendChild(dropdown);

  function _esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _doneCount(r) {
    return (r.passed || 0) + (r.failed || 0) + (r.error_count || 0);
  }

  function _render() {
    const viewedId = getCurrentViewedRunId ? getCurrentViewedRunId() : null;
    const visible = _runs.filter(r => r.id !== viewedId);

    if (!visible.length) {
      chip.style.display = 'none';
      dropdown.style.display = 'none';
      _dropdownOpen = false;
      return;
    }
    chip.style.display = 'inline-flex';

    if (visible.length === 1) {
      const r = visible[0];
      label.textContent = `● Running: ${r.collection_name} ${_doneCount(r)}/${r.total || 0}`;
      dropdown.style.display = 'none';
      dropdown.innerHTML = '';
      chip.onclick = () => onJump(r.id, r.collection_id, r.collection_name);
      return;
    }

    label.textContent = `● ${visible.length} running ▾`;
    dropdown.innerHTML = visible.map(r => `
      <div class="rsc-row" data-run-id="${_esc(r.id)}" data-col-id="${_esc(r.collection_id)}" data-col-name="${_esc(r.collection_name)}"
        style="padding:8px 12px;font-size:12px;font-weight:500;color:var(--text-primary);cursor:pointer;border-bottom:1px solid var(--border-subtle);">
        ${_esc(r.collection_name)}
        <span style="color:var(--text-muted);font-weight:400;"> ${_doneCount(r)}/${r.total || 0}</span>
      </div>`).join('');

    dropdown.querySelectorAll('.rsc-row').forEach(row => {
      row.onmouseenter = () => { row.style.background = 'var(--bg-panel)'; };
      row.onmouseleave = () => { row.style.background = ''; };
      row.onclick = (e) => {
        e.stopPropagation();
        onJump(row.dataset.runId, row.dataset.colId, row.dataset.colName);
      };
    });

    dropdown.style.display = _dropdownOpen ? 'block' : 'none';
    chip.onclick = (e) => {
      if (dropdown.contains(e.target)) return;
      _dropdownOpen = !_dropdownOpen;
      dropdown.style.display = _dropdownOpen ? 'block' : 'none';
    };
  }

  document.addEventListener('click', (e) => {
    if (_dropdownOpen && !chip.contains(e.target)) {
      _dropdownOpen = false;
      dropdown.style.display = 'none';
    }
  });

  function update(runs) { _runs = runs || []; _render(); }
  function refresh() { _render(); }

  return { update, refresh };
}
```

- [ ] **Step 2: Syntax-check the file**

Run: `node --check web/static/api/components/run-status-chip.js`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/components/run-status-chip.js
git commit -m "feat(api): add top-bar run-status chip component"
```

---

### Task 3: Completion notifier (sticky banner + OS notification)

**Files:**
- Create: `web/static/api/components/run-notification.js`

**Interfaces:**
- Consumes: nothing external — pure DOM + `Notification` browser API.
- Produces: `notifyRunCompleted(run, { onView }) -> void` and `maybeRequestPermission() -> void`. `run` is the object passed to Task 1's `onCompleted` (has `collection_name`, `status`, `passed`, `failed`, `error_count`). `onView()` is called when the user clicks either the banner's "View Results" button or the OS notification itself.

- [ ] **Step 1: Create the notification module**

```js
/**
 * notifyRunCompleted(run, { onView }): shows a sticky in-app banner (does
 * not auto-dismiss) and, if OS notification permission is granted, a native
 * Notification too. Both call onView() on click.
 *
 * maybeRequestPermission(): call once, right after a run is detected as
 * newly-started, to ask for OS notification permission via that user
 * gesture rather than on cold page load. No-ops after the first call, or if
 * permission has already been decided.
 */
let _permissionAsked = false;
let _stackEl = null;

function _esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _ensureStack() {
  if (_stackEl) return _stackEl;
  _stackEl = document.createElement('div');
  _stackEl.id = 'run-notification-stack';
  _stackEl.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:10001;' +
    'display:flex;flex-direction:column;gap:8px;align-items:flex-end;';
  document.body.appendChild(_stackEl);
  return _stackEl;
}

function _summaryText(run) {
  const parts = [`${run.passed || 0} passed`, `${run.failed || 0} failed`];
  if (run.error_count) parts.push(`${run.error_count} errors`);
  return parts.join(', ');
}

function _showBanner(run, summary, onView) {
  const stack = _ensureStack();
  const isPass = run.status === 'PASSED';
  const borderColor = isPass ? 'var(--success-border)' : 'var(--danger-border)';
  const titleColor = isPass ? 'var(--success)' : 'var(--danger)';

  const banner = document.createElement('div');
  banner.style.cssText = `background:var(--bg-elevated);border:1px solid ${borderColor};` +
    'border-radius:8px;padding:10px 14px;min-width:260px;max-width:340px;' +
    'box-shadow:var(--shadow-lg);font-size:12px;';
  banner.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
      <div>
        <div style="font-weight:700;color:${titleColor};margin-bottom:2px;">${_esc(run.collection_name)} finished</div>
        <div style="color:var(--text-secondary);">${_esc(summary)}</div>
      </div>
      <button class="rn-dismiss" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px;line-height:1;padding:0;">&#10005;</button>
    </div>
    <button class="rn-view btn btn-xs btn-primary" style="margin-top:8px;width:100%;">View Results</button>`;

  banner.querySelector('.rn-dismiss').onclick = () => banner.remove();
  banner.querySelector('.rn-view').onclick = () => { banner.remove(); onView(); };
  stack.appendChild(banner);
}

function _fireOsNotification(run, summary, onView) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    const n = new Notification(`${run.collection_name} finished`, { body: summary });
    n.onclick = () => { window.focus(); onView(); n.close(); };
  } catch (_) {}
}

export function notifyRunCompleted(run, { onView }) {
  const summary = _summaryText(run);
  _showBanner(run, summary, onView);
  _fireOsNotification(run, summary, onView);
}

export function maybeRequestPermission() {
  if (_permissionAsked) return;
  if (typeof Notification === 'undefined') return;
  if (Notification.permission !== 'default') return;
  _permissionAsked = true;
  Notification.requestPermission().catch(() => {});
}
```

- [ ] **Step 2: Syntax-check the file**

Run: `node --check web/static/api/components/run-notification.js`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/components/run-notification.js
git commit -m "feat(api): add sticky banner + OS notification for run completion"
```

---

### Task 4: Refactor sidebar dots to consume the shared tracker instead of self-polling

**Files:**
- Modify: `web/static/api/views/collections-view.js:10-71`

**Interfaces:**
- Consumes: nothing new — this task just removes the view's own polling and exposes a setter Task 5's tracker wiring will drive instead.
- Produces: adds `updateRunningRuns(runs)` to the object `renderCollectionsView` returns, alongside the existing `reload` and `setActiveRequestId`. Task 5 destructures this.

- [ ] **Step 1: Remove the self-poll and add `updateRunningRuns`**

Change:

```js
  let _runningByColId = {};
  let _runningPollTimer = null;
  let _activeRequestId = null; // re-applied to the matching row after every reload()
  const _scrollParent = container.closest('.api-sidebar') || container;
  let _savedScrollTop = 0; // restored after reload() and after each collection's async tree load

  async function _refreshRunningStatus() {
    try {
      const res = await window.api('GET', '/api-collection-runs?status=RUNNING');
      const runs = res.runs || [];
      const fresh = {};
      runs.forEach(r => { if (r.collection_id) fresh[r.collection_id] = r.id; });
      const changed = JSON.stringify(fresh) !== JSON.stringify(_runningByColId);
      _runningByColId = fresh;
      if (changed) _updateRunningDots();
      if (Object.keys(_runningByColId).length === 0 && _runningPollTimer) {
        clearInterval(_runningPollTimer);
        _runningPollTimer = null;
      }
    } catch (_) {}
  }

  function _updateRunningDots() {
```

to:

```js
  let _runningByColId = {};
  let _activeRequestId = null; // re-applied to the matching row after every reload()
  const _scrollParent = container.closest('.api-sidebar') || container;
  let _savedScrollTop = 0; // restored after reload() and after each collection's async tree load

  // Fed by the shared active-runs-tracker in api-section.js — this view no
  // longer polls the RUNNING endpoint itself, since the top-bar run-status
  // chip already polls it once for the whole page.
  function updateRunningRuns(runs) {
    const fresh = {};
    (runs || []).forEach(r => { if (r.collection_id) fresh[r.collection_id] = r.id; });
    const changed = JSON.stringify(fresh) !== JSON.stringify(_runningByColId);
    _runningByColId = fresh;
    if (changed) _updateRunningDots();
  }

  function _updateRunningDots() {
```

- [ ] **Step 2: Replace the reload-time poll kickoff with a plain dots refresh**

Change:

```js
    collections.forEach(col => container.appendChild(_renderCollectionSection(col)));
    _appendNewCollectionButton();
    _wireCollectionOrderDrag();
    _reapplyActiveRow();
    _scrollParent.scrollTop = _savedScrollTop;

    if (_runningPollTimer) clearInterval(_runningPollTimer);
    await _refreshRunningStatus();
    _runningPollTimer = setInterval(_refreshRunningStatus, 3000);
  }
```

to:

```js
    collections.forEach(col => container.appendChild(_renderCollectionSection(col)));
    _appendNewCollectionButton();
    _wireCollectionOrderDrag();
    _reapplyActiveRow();
    _scrollParent.scrollTop = _savedScrollTop;
    _updateRunningDots();
  }
```

- [ ] **Step 3: Export the new function from the view**

Change:

```js
  reload();
  return { reload, setActiveRequestId };
}
```

to:

```js
  reload();
  return { reload, setActiveRequestId, updateRunningRuns };
}
```

- [ ] **Step 4: Syntax-check the file**

Run: `node --check web/static/api/views/collections-view.js`
Expected: no output, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add web/static/api/views/collections-view.js
git commit -m "refactor(api): sidebar running-dots consume shared tracker instead of self-polling"
```

---

### Task 5: Wire tracker + chip + notifications into api-section.js

**Files:**
- Modify: `web/static/api/api-section.js:1-4` (add imports)
- Modify: `web/static/api/api-section.js:148-149` (add chip slot to top bar)
- Modify: `web/static/api/api-section.js:208-215` (track `_currentlyViewedRunId`)
- Modify: `web/static/api/api-section.js:236-239` (`_showRunDetail` sets/refreshes it)
- Modify: `web/static/api/api-section.js:250-268` (destructure `updateRunningRuns`, mount chip, start tracker)

**Interfaces:**
- Consumes: `startActiveRunsTracker` from Task 1, `mountRunStatusChip` from Task 2, `notifyRunCompleted`/`maybeRequestPermission` from Task 3, and `updateRunningRuns` which Task 4 added to `renderCollectionsView`'s return value.
- Produces: nothing new consumed elsewhere; this is the integration point.

- [ ] **Step 1: Add static imports at the top of the file**

In `web/static/api/api-section.js`, change:

```js
/**
 * API Section entry point.
 * Exposes window.__qaclanApi = { render(container) }
 */

if (!window.api) {
```

to:

```js
/**
 * API Section entry point.
 * Exposes window.__qaclanApi = { render(container) }
 */
import { startActiveRunsTracker } from './services/active-runs-tracker.js';
import { mountRunStatusChip } from './components/run-status-chip.js';
import { notifyRunCompleted, maybeRequestPermission } from './components/run-notification.js';

if (!window.api) {
```

- [ ] **Step 2: Add the chip's mount slot to the top bar**

Change:

```js
  topBar.appendChild(tabCollections);
  topBar.appendChild(tabDocs);
```

to:

```js
  topBar.appendChild(tabCollections);
  topBar.appendChild(tabDocs);

  const chipSlot = document.createElement('div');
  chipSlot.id = 'api-run-chip-slot';
  chipSlot.style.cssText = 'margin-left:auto;display:flex;align-items:center;';
  topBar.appendChild(chipSlot);
```

- [ ] **Step 3: Track which run (if any) is currently on screen**

Change:

```js
    const mainEl = () => document.getElementById('api-main-content');

    function _teardown() {
      const el = mainEl();
      if (el && el.__destroyRunView) { el.__destroyRunView(); el.__destroyRunView = null; }
      window.__qaclanApi.isCurrentEditorDirty = null;
      window.__qaclanApi.getCurrentEditorRequestId = null;
    }
```

to:

```js
    const mainEl = () => document.getElementById('api-main-content');
    let _currentlyViewedRunId = null;

    function _teardown() {
      const el = mainEl();
      if (el && el.__destroyRunView) { el.__destroyRunView(); el.__destroyRunView = null; }
      window.__qaclanApi.isCurrentEditorDirty = null;
      window.__qaclanApi.getCurrentEditorRequestId = null;
      _currentlyViewedRunId = null;
    }
```

`_teardown()` runs on every navigation away from any view (`_emptyMain`, `_showCollectionDetail`, opening the request editor), so this one spot is enough to clear the flag everywhere except where it's explicitly set below.

- [ ] **Step 4: Set the flag (and refresh the chip instantly) when opening a run**

Change:

```js
    function _showRunDetail(runId, colId, colName) {
      _teardown();
      renderCollectionRunView(mainEl(), runId, colId, colName, _emptyMain);
    }
```

to:

```js
    function _showRunDetail(runId, colId, colName) {
      _teardown();
      _currentlyViewedRunId = runId;
      _runChip.refresh();
      renderCollectionRunView(mainEl(), runId, colId, colName, _emptyMain);
    }
```

- [ ] **Step 5: Destructure `updateRunningRuns` and mount the chip + tracker**

Change:

```js
    const { reload: _reloadCollections, setActiveRequestId: _setActiveRequestId } = renderCollectionsView(
      document.getElementById('api-collections-panel'),
      async (requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId) => {
        if (!(await _confirmDiscardIfDirty())) return false;
        _teardown();
        renderRequestEditor(mainEl(), requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId);
      },
      (runId, colId, colName) => _showRunDetail(runId, colId, colName),
      async (col, runId) => {
        if (!(await _confirmDiscardIfDirty())) return false;
        _showCollectionDetail(col, runId);
      }
    );
    // requestId (when given) is the just-saved request — keeps it highlighted
    // as selected across the list rebuild instead of losing the highlight.
    window.__qaclanApi.refresh = (requestId) => {
      if (requestId !== undefined) _setActiveRequestId(requestId);
      return _reloadCollections();
    };
```

to:

```js
    const {
      reload: _reloadCollections,
      setActiveRequestId: _setActiveRequestId,
      updateRunningRuns: _updateRunningRuns,
    } = renderCollectionsView(
      document.getElementById('api-collections-panel'),
      async (requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId) => {
        if (!(await _confirmDiscardIfDirty())) return false;
        _teardown();
        renderRequestEditor(mainEl(), requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId);
      },
      (runId, colId, colName) => _showRunDetail(runId, colId, colName),
      async (col, runId) => {
        if (!(await _confirmDiscardIfDirty())) return false;
        _showCollectionDetail(col, runId);
      }
    );
    // requestId (when given) is the just-saved request — keeps it highlighted
    // as selected across the list rebuild instead of losing the highlight.
    window.__qaclanApi.refresh = (requestId) => {
      if (requestId !== undefined) _setActiveRequestId(requestId);
      return _reloadCollections();
    };

    // Top-bar run-status chip + completion notifications, both fed by one
    // shared poller (also feeds the sidebar's running-dots via _updateRunningRuns).
    const _runChip = mountRunStatusChip(document.getElementById('api-run-chip-slot'), {
      getCurrentViewedRunId: () => _currentlyViewedRunId,
      onJump: (runId, colId, colName) => _showRunDetail(runId, colId, colName),
    });

    let _prevRunningCount = 0;
    startActiveRunsTracker({
      onChange: (runs) => {
        _runChip.update(runs);
        _updateRunningRuns(runs);
        if (_prevRunningCount === 0 && runs.length > 0) maybeRequestPermission();
        _prevRunningCount = runs.length;
      },
      onCompleted: (run) => {
        if (run.id === _currentlyViewedRunId) return;
        notifyRunCompleted(run, {
          onView: () => _showRunDetail(run.id, run.collection_id, run.collection_name),
        });
      },
    });
```

- [ ] **Step 6: Syntax-check the file**

Run: `node --check web/static/api/api-section.js`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add web/static/api/api-section.js
git commit -m "feat(api): wire run-status chip and completion notifications into api-section"
```

---

### Task 6: End-to-end manual verification

**Files:** none (verification only; fix forward in the relevant file from Tasks 1-5 if something fails, then re-run this task).

- [ ] **Step 1: Start the dev server**

Run: `python qaclan.py serve --port 7823`
Expected: server starts, no traceback in the console.

- [ ] **Step 2: Chip appears and jumps back correctly**

In a browser, open `http://localhost:7823`, go to the API section, click "▶ Run collection" on any collection with 2+ requests. While the run view is open, click a different request in the sidebar to open the request editor.
Expected: a chip reading `● Running: <name> n/total` appears at the right edge of the Collections/API Docs tab bar. Click it.
Expected: it jumps straight back to that run's live view (not the collection-detail intermediate screen).

- [ ] **Step 3: Chip suppresses itself on the run's own page**

While still on that run's live view (from Step 2), look at the top bar.
Expected: the chip is not shown (since `getCurrentViewedRunId()` matches the run on screen).

- [ ] **Step 4: Sticky banner on completion, not auto-dismissing**

Let the run finish while the chip is visible (i.e., you're not on its page). Wait for it to complete (or run a collection with fast requests).
Expected: within ~3s of completion, a banner appears bottom-right with the collection name, "finished", and a passed/failed/error summary. Wait 10+ seconds.
Expected: banner is still there (no auto-dismiss).

- [ ] **Step 5: Banner "View Results" navigates and clears**

Click "View Results" on the banner from Step 4.
Expected: banner disappears immediately, and the run's live view opens showing the final PASSED/FAILED state and per-request rows.

- [ ] **Step 6: Multiple concurrent runs**

Start two different collections running at (roughly) the same time.
Expected: chip shows `● 2 running ▾`; clicking it opens a dropdown listing both by name with their own progress; clicking a row jumps to that run specifically.

- [ ] **Step 7: OS notification permission flow**

Reload the page fresh (clear any prior `Notification.permission` decision via browser site settings if needed), then start a run.
Expected: browser prompts for notification permission shortly after the run starts (not on page load). Grant it, then let this or a subsequent run finish while the tab is unfocused/minimized.
Expected: a native OS notification appears with the collection name and summary; clicking it focuses the tab and opens the run's live view.

- [ ] **Step 8: Denied-permission fallback**

In a browser profile/site where notification permission is denied, finish a run.
Expected: no OS notification appears, but the in-app sticky banner still shows correctly, and the browser console has no errors.

- [ ] **Step 9: Sidebar dots still work**

With the refactor from Task 5 in place, start a run and watch the sidebar.
Expected: the collection's pulsing dot (next to its name) still appears while running and disappears once it finishes — same as before, just now driven by the shared tracker instead of its own poll.

- [ ] **Step 10: Final commit (only if Step 1-9 surfaced fixes)**

If any step above required a code fix, stage exactly the files touched and commit:

```bash
git add <fixed files>
git commit -m "fix(api): address issues found in run-status manual verification"
```

If no fixes were needed, skip this step — Tasks 1-5's commits already cover everything.
