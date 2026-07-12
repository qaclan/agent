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
