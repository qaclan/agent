import os
import sqlite3
import threading
import uuid

from cli.config import QACLAN_DIR, ensure_dirs

DB_PATH = os.path.join(QACLAN_DIR, "qaclan.db")

_local = threading.local()


def get_conn():
    conn = getattr(_local, 'conn', None)
    if conn is None:
        ensure_dirs()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def generate_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS features (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            description TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scripts (
            id TEXT PRIMARY KEY,
            feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS environments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS env_vars (
            id TEXT PRIMARY KEY,
            environment_id TEXT NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            is_secret INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS suites (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            first_run_at TEXT,
            last_run_at TEXT,
            last_run_status TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suite_items (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
            script_id TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suite_runs (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL,
            environment_id TEXT REFERENCES environments(id) ON DELETE SET NULL,
            channel TEXT NOT NULL DEFAULT 'web',
            status TEXT NOT NULL DEFAULT 'RUNNING',
            total INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS script_runs (
            id TEXT PRIMARY KEY,
            suite_run_id TEXT NOT NULL REFERENCES suite_runs(id) ON DELETE CASCADE,
            script_id TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            duration_ms INTEGER,
            console_errors INTEGER DEFAULT 0,
            network_failures INTEGER DEFAULT 0,
            error_message TEXT,
            started_at TEXT,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS step_runs (
            id TEXT PRIMARY KEY,
            script_run_id TEXT NOT NULL REFERENCES script_runs(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL,
            action TEXT,
            locator TEXT,
            status TEXT,
            duration_ms INTEGER,
            error_message TEXT
        );
    """)
    conn.commit()
    _migrate_cloud_id(conn)
    _migrate_cascade(conn)
    _migrate_run_diagnostics(conn)
    _migrate_created_by(conn)
    _migrate_run_options(conn)
    _migrate_script_templating(conn)


def _migrate_script_templating(conn):
    """Add columns to support env-aware recording: start URL provenance + var dependencies."""
    for ddl in (
        "ALTER TABLE scripts ADD COLUMN start_url_key TEXT",
        "ALTER TABLE scripts ADD COLUMN start_url_value TEXT",
        "ALTER TABLE scripts ADD COLUMN var_keys TEXT DEFAULT '[]'",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            pass  # Column already exists
    conn.commit()


def _migrate_cloud_id(conn):
    """Add cloud_id column to tables that sync with the cloud server."""
    for table in ("projects", "features", "suites", "scripts", "environments"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN cloud_id TEXT")
        except Exception:
            pass  # Column already exists
    conn.commit()


def _migrate_cascade(conn):
    """Recreate tables to add ON DELETE CASCADE if missing (one-time migration)."""
    # Check if migration already applied by looking for cascade in schema
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='features'"
    ).fetchone()
    if schema and "ON DELETE CASCADE" in (schema[0] or ""):
        return  # Already migrated

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("""
        BEGIN;

        -- features
        ALTER TABLE features RENAME TO _features_old;
        CREATE TABLE features (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            description TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO features SELECT * FROM _features_old;
        DROP TABLE _features_old;

        -- scripts
        ALTER TABLE scripts RENAME TO _scripts_old;
        CREATE TABLE scripts (
            id TEXT PRIMARY KEY,
            feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO scripts SELECT * FROM _scripts_old;
        DROP TABLE _scripts_old;

        -- environments
        ALTER TABLE environments RENAME TO _environments_old;
        CREATE TABLE environments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO environments SELECT * FROM _environments_old;
        DROP TABLE _environments_old;

        -- env_vars
        ALTER TABLE env_vars RENAME TO _env_vars_old;
        CREATE TABLE env_vars (
            id TEXT PRIMARY KEY,
            environment_id TEXT NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            is_secret INTEGER DEFAULT 0
        );
        INSERT INTO env_vars SELECT * FROM _env_vars_old;
        DROP TABLE _env_vars_old;

        -- suites
        ALTER TABLE suites RENAME TO _suites_old;
        CREATE TABLE suites (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            first_run_at TEXT,
            last_run_at TEXT,
            last_run_status TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO suites SELECT * FROM _suites_old;
        DROP TABLE _suites_old;

        -- suite_items
        ALTER TABLE suite_items RENAME TO _suite_items_old;
        CREATE TABLE suite_items (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
            script_id TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        INSERT INTO suite_items SELECT * FROM _suite_items_old;
        DROP TABLE _suite_items_old;

        -- suite_runs
        ALTER TABLE suite_runs RENAME TO _suite_runs_old;
        CREATE TABLE suite_runs (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL,
            environment_id TEXT REFERENCES environments(id) ON DELETE SET NULL,
            channel TEXT NOT NULL DEFAULT 'web',
            status TEXT NOT NULL DEFAULT 'RUNNING',
            total INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        INSERT INTO suite_runs SELECT * FROM _suite_runs_old;
        DROP TABLE _suite_runs_old;

        -- script_runs
        ALTER TABLE script_runs RENAME TO _script_runs_old;
        CREATE TABLE script_runs (
            id TEXT PRIMARY KEY,
            suite_run_id TEXT NOT NULL REFERENCES suite_runs(id) ON DELETE CASCADE,
            script_id TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            duration_ms INTEGER,
            console_errors INTEGER DEFAULT 0,
            network_failures INTEGER DEFAULT 0,
            error_message TEXT,
            started_at TEXT,
            finished_at TEXT
        );
        INSERT INTO script_runs SELECT * FROM _script_runs_old;
        DROP TABLE _script_runs_old;

        -- step_runs
        ALTER TABLE step_runs RENAME TO _step_runs_old;
        CREATE TABLE step_runs (
            id TEXT PRIMARY KEY,
            script_run_id TEXT NOT NULL REFERENCES script_runs(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL,
            action TEXT,
            locator TEXT,
            status TEXT,
            duration_ms INTEGER,
            error_message TEXT
        );
        INSERT INTO step_runs SELECT * FROM _step_runs_old;
        DROP TABLE _step_runs_old;

        COMMIT;
    """)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def _migrate_created_by(conn):
    """Add created_by column to scripts table."""
    try:
        conn.execute("ALTER TABLE scripts ADD COLUMN created_by TEXT")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _migrate_run_options(conn):
    """Add browser, resolution, headless columns to suite_runs."""
    for col, coltype in [("browser", "TEXT"), ("resolution", "TEXT"), ("headless", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE suite_runs ADD COLUMN {col} {coltype}")
        except Exception:
            pass
    conn.commit()


def _migrate_run_diagnostics(conn):
    """Add screenshot_path, console_log, and network_log columns to script_runs."""
    for col, coltype in [
        ("screenshot_path", "TEXT"),
        ("console_log", "TEXT"),
        ("network_log", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE script_runs ADD COLUMN {col} {coltype}")
        except Exception:
            pass  # Column already exists
    conn.commit()
