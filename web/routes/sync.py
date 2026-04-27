from flask import Blueprint, jsonify

from cli.config import get_active_project_id, get_auth_key
from cli.sync_queue import enqueue_all, flush_sync, queue_depth, trigger_now

bp = Blueprint('sync', __name__, url_prefix='/api/sync')


def _require_auth():
    if not get_auth_key():
        return jsonify({"ok": False, "error": "Not logged in. Add your auth key in Settings."}), 401
    return None


@bp.route('/push', methods=['POST'])
def push_now():
    """Re-enqueue every local entity for the active project (or all if none set)
    then flush the queue with a short deadline. Anything that didn't drain in
    time stays in the queue for the background worker."""
    err = _require_auth()
    if err:
        return err
    pid = get_active_project_id()
    project_ids = [pid] if pid else None
    queued, _ = enqueue_all(project_ids)
    trigger_now()
    flush_sync(deadline=30)
    remaining = queue_depth()
    return jsonify({
        "ok": True,
        "queued": queued,
        "remaining": remaining,
        "message": (
            f"Push complete — {queued} item(s) enqueued"
            if remaining == 0
            else f"{queued} enqueued; {remaining} still pending, will retry in background"
        ),
    }), 200


@bp.route('/pull', methods=['POST'])
def pull_now():
    """Fetch workspace from cloud and merge into local DB."""
    err = _require_auth()
    if err:
        return err
    from cli.commands.pull import pull_workspace
    try:
        counts = pull_workspace()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    total = sum(counts.values())
    return jsonify({
        "ok": True,
        "counts": counts,
        "message": (
            "Everything up to date"
            if total == 0
            else f"Pulled {counts['projects']} projects, {counts['features']} features, "
                 f"{counts['scripts']} scripts, {counts['suites']} suites, "
                 f"{counts['environments']} environments, {counts['env_vars']} env vars"
        ),
    }), 200


@bp.route('/status', methods=['GET'])
def sync_status():
    return jsonify({"ok": True, "queue_depth": queue_depth()}), 200
