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
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _write_config(data):
    ensure_dirs()
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_active_project_id():
    cfg = _read_config()
    return cfg.get("active_project")


def set_active_project_id(project_id):
    cfg = _read_config()
    cfg["active_project"] = project_id
    _write_config(cfg)


# DEFAULT_SERVER_URL = os.environ.get("QACLAN_SERVER_URL", "https://qaclan.com")
DEFAULT_SERVER_URL = os.environ.get("QACLAN_SERVER_URL", "http://127.0.0.1:5000")

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
    "username": ["user", "username", "email", "login", "userid", "e-mail"],
    "password": ["pass", "password", "pwd", "passwd"],
    "tenant":   ["tenant", "org", "organization", "workspace", "account"],
    "token":    ["token", "api_key", "apikey", "secret", "access_key"],
    "otp":      ["otp", "code", "2fa", "mfa", "pin", "verification"],
    "client":   ["client_id", "clientid", "client_secret"],
    "host":     ["host", "base_url", "endpoint"],
}

# Categories whose recorded values should be masked in the UI and never logged at runtime.
SECRET_CATEGORIES = {"password", "token", "otp", "client"}


def get_sensitive_field_patterns():
    """Return active sensitive-field patterns: defaults merged with user overrides."""
    cfg = _read_config()
    user_patterns = cfg.get("sensitive_field_patterns", {})
    merged = {k: list(v) for k, v in DEFAULT_SENSITIVE_PATTERNS.items()}
    if isinstance(user_patterns, dict):
        for category, patterns in user_patterns.items():
            if isinstance(patterns, list):
                merged[category] = patterns
    return merged
