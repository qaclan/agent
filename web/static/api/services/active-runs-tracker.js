/**
 * startActiveRunsTracker({ onChange, onCompleted }) -> { stop, notifyRunStarted }
 * Poller for GET /api-collection-runs?status=RUNNING, active only while a run
 * is in flight. Does one check on mount (to pick up a run already RUNNING
 * from a prior session/reload); if none is found it stays idle — no interval,
 * no repeated hits — until notifyRunStarted() is called or a tick finds a run.
 * Polls every 3s while at least one run is RUNNING, and stops itself the
 * moment a tick comes back empty.
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

  function _ensurePolling() {
    if (_timer || _stopped) return;
    _timer = setInterval(_tick, 3000);
  }

  function _stopPolling() {
    if (_timer) { clearInterval(_timer); _timer = null; }
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

      if (curIds.size > 0) _ensurePolling();
      else _stopPolling();
    } catch (_) {}
  }

  _tick();

  return {
    stop() {
      _stopped = true;
      _stopPolling();
    },
    // Call right after a run is kicked off, so the tracker starts polling
    // immediately instead of waiting for the next tick (there isn't one, idle).
    notifyRunStarted() {
      if (_stopped) return;
      _tick();
      _ensurePolling();
    },
  };
}
