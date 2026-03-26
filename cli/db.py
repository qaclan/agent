import os
import sqlite3
import uuid

from cli.config import QACLAN_DIR, ensure_dirs

DB_PATH = os.path.join(QACLAN_DIR, "qaclan.db")

_conn = None


def get_conn():
    global _conn
    if _conn is None:
        ensure_dirs()
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


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
            project_id TEXT NOT NULL REFERENCES projects(id),
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            description TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scripts (
            id TEXT PRIMARY KEY,
            feature_id TEXT NOT NULL REFERENCES features(id),
            project_id TEXT NOT NULL REFERENCES projects(id),
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS environments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS env_vars (
            id TEXT PRIMARY KEY,
            environment_id TEXT NOT NULL REFERENCES environments(id),
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            is_secret INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS suites (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            channel TEXT NOT NULL DEFAULT 'web',
            name TEXT NOT NULL,
            first_run_at TEXT,
            last_run_at TEXT,
            last_run_status TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suite_items (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES suites(id),
            script_id TEXT NOT NULL REFERENCES scripts(id),
            order_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suite_runs (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES suites(id),
            project_id TEXT NOT NULL,
            environment_id TEXT REFERENCES environments(id),
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
            suite_run_id TEXT NOT NULL REFERENCES suite_runs(id),
            script_id TEXT NOT NULL REFERENCES scripts(id),
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
            script_run_id TEXT NOT NULL REFERENCES script_runs(id),
            order_index INTEGER NOT NULL,
            action TEXT,
            locator TEXT,
            status TEXT,
            duration_ms INTEGER,
            error_message TEXT
        );
    """)
    conn.commit()
