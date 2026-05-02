import json
import os

QACLAN_DIR = os.path.expanduser("~/.qaclan")
CONFIG_PATH = os.path.join(QACLAN_DIR, "config.json")
SCRIPTS_DIR = os.path.join(QACLAN_DIR, "scripts")


def ensure_dirs():
    os.makedirs(QACLAN_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)


def _read_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_config(data):
    ensure_dirs()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_active_project_id():
    cfg = _read_config()
    return cfg.get("active_project")


def set_active_project_id(project_id):
    cfg = _read_config()
    cfg["active_project"] = project_id
    _write_config(cfg)


DEFAULT_SERVER_URL = os.environ.get("QACLAN_SERVER_URL", "https://qaclan.com")

def get_auth_key():
    cfg = _read_config()
    return cfg.get("auth_key")


def set_auth_key(key):
    cfg = _read_config()
    cfg["auth_key"] = key
    _write_config(cfg)


def remove_auth_key():
    cfg = _read_config()
    cfg.pop("auth_key", None)
    _write_config(cfg)


def get_user_name():
    cfg = _read_config()
    return cfg.get("user_name")


def set_user_name(name):
    cfg = _read_config()
    cfg["user_name"] = name
    _write_config(cfg)


def get_server_url():
    cfg = _read_config()
    return cfg.get("server_url", DEFAULT_SERVER_URL)


def set_server_url(url):
    cfg = _read_config()
    cfg["server_url"] = url
    _write_config(cfg)


def get_active_project(console):
    """Get the active project row from DB. Prints error and returns None if not set."""
    from cli.db import get_conn

    project_id = get_active_project_id()
    if not project_id:
        console.print("[red]No active project. Run: qaclan project create \"name\"[/red]")
        return None
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        console.print("[red]No active project. Run: qaclan project create \"name\"[/red]")
        return None
    return row


# Built-in patterns for sensitive form fields. Categories map to substring matches
# (case-insensitive) against the locator text of .fill() calls. Users can extend
# or override these by adding "sensitive_field_patterns" to ~/.qaclan/config.json.
DEFAULT_SENSITIVE_PATTERNS = {
    "username": {"patterns": ["user", "username", "email", "login", "userid", "e-mail"], "canonical_key": "username"},
    "password": {"patterns": ["pass", "password", "pwd", "passwd"], "canonical_key": "password"},
    "tenant":   {"patterns": ["tenant", "org", "organization", "workspace", "account"], "canonical_key": "tenant_id"},
    "token":    {"patterns": ["token", "api_key", "apikey", "secret", "access_key"], "canonical_key": "api_token"},
    "otp":      {"patterns": ["otp", "code", "2fa", "mfa", "pin", "verification"], "canonical_key": "otp_code"},
    "client":   {"patterns": ["client_id", "clientid", "client_secret"], "canonical_key": "client_id"},
    "host":     {"patterns": ["host", "base_url", "endpoint"], "canonical_key": "base_url"},
}

# Categories whose recorded values should be masked in the UI and never logged at runtime.
SECRET_CATEGORIES = {"password", "token", "otp", "client"}


def get_sensitive_field_patterns():
    """Return active sensitive-field patterns: defaults merged with user overrides.

    Returns dict of { category: { patterns: [...], canonical_key: "..." } }.
    User overrides can be either the new dict shape or the old list-only shape
    (for backward compat with existing config.json files).
    """
    cfg = _read_config()
    user_patterns = cfg.get("sensitive_field_patterns", {})
    merged = {k: dict(v) for k, v in DEFAULT_SENSITIVE_PATTERNS.items()}
    if isinstance(user_patterns, dict):
        for category, val in user_patterns.items():
            if isinstance(val, dict):
                # New shape: { patterns: [...], canonical_key: "..." }
                merged[category] = val
            elif isinstance(val, list):
                # Old shape: just a list of patterns — preserve existing canonical_key if category exists
                existing = merged.get(category, {})
                merged[category] = {"patterns": val, "canonical_key": existing.get("canonical_key", category.upper())}
    return merged


# Editor preference for the script editor UI. Shipped as "code" by default
# (syntax-highlighted CodeMirror 6). Can be flipped to "text" for a plain
# textarea — useful as a fallback or for minimal-JS environments.
#
# Resolution order (first non-empty wins):
#   1. QACLAN_EDITOR_MODE environment variable (dev override)
#   2. "editor_mode" field in ~/.qaclan/config.json (per-user override)
#   3. DEFAULT_EDITOR_MODE constant below (shipped with the binary)
DEFAULT_EDITOR_MODE = os.environ.get("QACLAN_EDITOR_MODE", "code")
ALLOWED_EDITOR_MODES = ("code", "text")


def get_editor_mode():
    """Return the active script editor mode: 'code' or 'text'."""
    cfg = _read_config()
    mode = cfg.get("editor_mode") or DEFAULT_EDITOR_MODE
    if mode not in ALLOWED_EDITOR_MODES:
        mode = "code"
    return mode
