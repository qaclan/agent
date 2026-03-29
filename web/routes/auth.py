from flask import Blueprint, request, jsonify
from cli.config import get_auth_key, set_auth_key, remove_auth_key, get_server_url, set_server_url
from cli.api import validate_auth_key

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@bp.route('/status', methods=['GET'])
def auth_status():
    """Check if an auth key is stored and valid."""
    key = get_auth_key()
    if not key:
        return jsonify({"authenticated": False}), 200

    server_url = get_server_url()
    try:
        user = validate_auth_key(server_url, key)
    except Exception:
        return jsonify({"authenticated": True, "user": None, "error": "Could not reach server"}), 200

    if not user:
        return jsonify({"authenticated": False, "error": "Stored key is invalid"}), 200

    return jsonify({"authenticated": True, "user": user}), 200


@bp.route('/save', methods=['POST'])
def auth_save():
    """Validate and save an auth key."""
    data = request.get_json() or {}
    key = data.get('auth_key', '').strip()
    server_url = data.get('server_url', '').strip()

    if not key:
        return jsonify({"ok": False, "error": "Auth key is required"}), 400

    if server_url:
        set_server_url(server_url)

    url = get_server_url()
    try:
        user = validate_auth_key(url, key)
    except Exception:
        return jsonify({"ok": False, "error": f"Could not reach server at {url}"}), 502

    if not user:
        return jsonify({"ok": False, "error": "Invalid auth key. Please check and try again."}), 401

    set_auth_key(key)
    return jsonify({"ok": True, "user": user}), 200


@bp.route('/remove', methods=['POST'])
def auth_remove():
    """Remove stored auth key (logout)."""
    remove_auth_key()
    return jsonify({"ok": True}), 200
