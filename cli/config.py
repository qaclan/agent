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
