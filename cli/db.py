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
    _migrate_script_language(conn)
    _migrate_script_wait_timeout(conn)
    _migrate_error_detail(conn)
    _migrate_api_tables(conn)
    _migrate_api_extractor(conn)
    _migrate_api_schemas(conn)
    _migrate_api_docs(conn)
    _migrate_var_picker(conn)
    _migrate_collection_auth(conn)
    _migrate_api_collection_runs(conn)


def _migrate_var_picker(conn):
    """Add env_name to api_collections, path_params to api_requests, create collection_vars."""
    try:
        conn.execute("ALTER TABLE api_collections ADD COLUMN env_name TEXT DEFAULT NULL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE api_requests ADD COLUMN path_params TEXT NOT NULL DEFAULT '[]'")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_vars (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            key TEXT NOT NULL,
            initial_value TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(collection_id, key),
            FOREIGN KEY(collection_id) REFERENCES api_collections(id) ON DELETE CASCADE
        )
    """)
    conn.commit()


def _migrate_collection_auth(conn):
    """Add auth_type and auth_config to api_collections for collection-level auth."""
    try:
        conn.execute("ALTER TABLE api_collections ADD COLUMN auth_type TEXT NOT NULL DEFAULT 'none'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE api_collections ADD COLUMN auth_config TEXT NOT NULL DEFAULT '{}'")
    except Exception:
        pass
    conn.commit()


def _migrate_api_collection_runs(conn):
    """Create api_collection_runs and api_request_results tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_collection_runs (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL,
            collection_id   TEXT NOT NULL REFERENCES api_collections(id) ON DELETE CASCADE,
            collection_name TEXT NOT NULL,
            env_name        TEXT,
            status          TEXT NOT NULL,
            total           INTEGER NOT NULL DEFAULT 0,
            passed          INTEGER NOT NULL DEFAULT 0,
            failed          INTEGER NOT NULL DEFAULT 0,
            error_count     INTEGER NOT NULL DEFAULT 0,
            started_at      TEXT NOT NULL,
            finished_at     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_request_results (
            id                TEXT PRIMARY KEY,
            collection_run_id TEXT NOT NULL REFERENCES api_collection_runs(id) ON DELETE CASCADE,
            api_request_id    TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
            request_name      TEXT NOT NULL,
            method            TEXT,
            url               TEXT,
            order_index       INTEGER NOT NULL DEFAULT 0,
            status            TEXT,
            status_code       INTEGER,
            response_body     TEXT,
            response_headers  TEXT,
            duration_ms       INTEGER,
            assertion_results TEXT,
            error_message     TEXT,
            started_at        TEXT,
            finished_at       TEXT
        )
    """)
    conn.commit()


def _migrate_error_detail(conn):
    """Add nullable error_detail column to script_runs — JSON of the structured
    error dict {category, title, message, next_step, severity, raw_type,
    selector, timeout_ms}. The raw blob stays in error_message. Old rows have
    error_detail = NULL and the UI falls back to error_message. See
    docs/error-reporting-plan.md (section 2.4)."""
    try:
        conn.execute("ALTER TABLE script_runs ADD COLUMN error_detail TEXT")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _migrate_api_tables(conn):
    """Create api_collections, api_requests, api_runs tables and extend suite_items."""
    # 1. api_collections
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_collections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # 2. api_requests
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_requests (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            feature_id TEXT REFERENCES features(id) ON DELETE SET NULL,
            collection_id TEXT REFERENCES api_collections(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'GET',
            url TEXT NOT NULL,
            headers TEXT NOT NULL DEFAULT '[]',
            params TEXT NOT NULL DEFAULT '[]',
            body_type TEXT DEFAULT NULL,
            body TEXT DEFAULT NULL,
            auth_type TEXT NOT NULL DEFAULT 'none',
            auth_config TEXT NOT NULL DEFAULT '{}',
            pre_script TEXT DEFAULT NULL,
            pre_lang TEXT DEFAULT 'js',
            post_script TEXT DEFAULT NULL,
            post_lang TEXT DEFAULT 'js',
            assertions TEXT NOT NULL DEFAULT '[]',
            follow_redirects INTEGER DEFAULT 1,
            timeout_ms INTEGER DEFAULT 30000,
            created_at TEXT NOT NULL
        )
    """)

    # 3. api_runs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_runs (
            id TEXT PRIMARY KEY,
            suite_run_id TEXT NOT NULL REFERENCES suite_runs(id) ON DELETE CASCADE,
            api_request_id TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            status_code INTEGER,
            response_body TEXT,
            response_headers TEXT,
            duration_ms INTEGER,
            assertion_results TEXT,
            error_message TEXT,
            started_at TEXT,
            finished_at TEXT
        )
    """)

    # 4. Recreate suite_items with nullable script_id + item_type + api_request_id
    #    Guard: skip if item_type column already exists
    has_item_type = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('suite_items') WHERE name='item_type'"
    ).fetchone()[0]
    if not has_item_type:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE suite_items RENAME TO _suite_items_old")
        conn.execute("""
            CREATE TABLE suite_items (
                id TEXT PRIMARY KEY,
                suite_id TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
                script_id TEXT REFERENCES scripts(id) ON DELETE CASCADE,
                api_request_id TEXT REFERENCES api_requests(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL DEFAULT 'script',
                order_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO suite_items (id, suite_id, script_id, item_type, order_index, created_at)
            SELECT id, suite_id, script_id, 'script', order_index, created_at
            FROM _suite_items_old
        """)
        conn.execute("DROP TABLE _suite_items_old")
        conn.execute("PRAGMA foreign_keys = ON")

    # 5. Add description column to suites (safe — nullable, no default needed)
    has_desc = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('suites') WHERE name='description'"
    ).fetchone()[0]
    if not has_desc:
        conn.execute("ALTER TABLE suites ADD COLUMN description TEXT")

    conn.commit()


def _migrate_api_extractor(conn):
    """Add post_extractor column to api_requests — JSON array of {path, name, prefix} rules."""
    try:
        conn.execute("ALTER TABLE api_requests ADD COLUMN post_extractor TEXT DEFAULT NULL")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _migrate_api_schemas(conn):
    """Add request_schema and response_schema columns — inferred JSON type trees from HAR."""
    for col in ("request_schema", "response_schema"):
        try:
            conn.execute(f"ALTER TABLE api_requests ADD COLUMN {col} TEXT DEFAULT NULL")
        except Exception:
            pass  # Column already exists
    conn.commit()


def _migrate_api_docs(conn):
    """Create api_doc_entries table and add include_in_docs to api_requests."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_doc_entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            method TEXT NOT NULL,
            path_pattern TEXT NOT NULL,
            description TEXT,
            request_schema TEXT DEFAULT NULL,
            response_schema TEXT DEFAULT NULL,
            headers_schema TEXT DEFAULT NULL,
            params_schema TEXT DEFAULT NULL,
            source_request_ids TEXT DEFAULT '[]',
            include_in_docs INTEGER DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
    """)
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_doc_entries_unique "
            "ON api_doc_entries(project_id, method, path_pattern)"
        )
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE api_requests ADD COLUMN include_in_docs INTEGER DEFAULT 1")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _migrate_script_wait_timeout(conn):
    """Add nullable wait_timeout column to scripts — per-script timeout override.
    NULL means 'inherit the run-level wait limit'. See
    docs/expect-timeout-strategy-plan.md (Layer 2)."""
    try:
        conn.execute("ALTER TABLE scripts ADD COLUMN wait_timeout INTEGER")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _migrate_script_language(conn):
    """Add language column so each script knows which runtime drives it."""
    try:
        conn.execute("ALTER TABLE scripts ADD COLUMN language TEXT NOT NULL DEFAULT 'python'")
    except Exception:
        pass  # Column already exists
    _migrate_sync_queue(conn)


def _migrate_sync_queue(conn):
    """Create the offline-tolerant sync queue table."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            op TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            last_attempt_at TEXT,
            UNIQUE(entity_type, entity_id, op)
        );
        CREATE INDEX IF NOT EXISTS idx_sync_queue_attempts ON sync_queue(attempts, id);
    """)
    conn.commit()


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
