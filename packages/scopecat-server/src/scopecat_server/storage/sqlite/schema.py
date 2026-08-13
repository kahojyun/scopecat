"""Current SQLite project-store schema."""

from scopecat_server.storage.sqlite.config_schema import CONFIG_REGISTRY_TABLES_SQL
from scopecat_server.storage.sqlite.execution_schema import EXECUTION_TABLES_SQL
from scopecat_server.storage.sqlite.run_schema import RUN_TABLES_SQL

PROJECT_SCHEMA_VERSION = 29

_CONTROL_TABLES_SQL = f"""
CREATE TABLE IF NOT EXISTS project_schema (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL
);

INSERT OR IGNORE INTO project_schema(singleton, version)
VALUES (1, {PROJECT_SCHEMA_VERSION});

CREATE TABLE IF NOT EXISTS scheduler_runs (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'leased', 'attention_required', 'closed')
    ),
    updated_at TEXT NOT NULL,
    admission_json TEXT NOT NULL,
    attention_reason TEXT,
    cancellation_requested_at TEXT,
    CHECK (
        (state = 'attention_required' AND attention_reason IS NOT NULL)
        OR (state <> 'attention_required' AND attention_reason IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS scheduler_runs_state_sequence
ON scheduler_runs(state, sequence);

CREATE TABLE IF NOT EXISTS run_resource_claims (
    run_id TEXT NOT NULL REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    PRIMARY KEY (run_id, resource_kind, resource_id)
);

CREATE TABLE IF NOT EXISTS durable_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    run_sequence INTEGER CHECK (run_sequence IS NULL OR run_sequence >= 0),
    deduplication_key TEXT
);

CREATE INDEX IF NOT EXISTS durable_events_run_id_event_id
ON durable_events(run_id, event_id);

CREATE UNIQUE INDEX IF NOT EXISTS durable_events_run_kind_sequence
ON durable_events(run_id, kind, run_sequence)
WHERE run_sequence IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS durable_events_run_kind_deduplication
ON durable_events(run_id, kind, deduplication_key)
WHERE deduplication_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS executor_leases (
    run_id TEXT PRIMARY KEY REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    executor_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_claims (
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK (
        owner_kind IN ('run', 'instrument_session')
    ),
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'quarantined')),
    acquired_at TEXT NOT NULL,
    PRIMARY KEY (resource_kind, resource_id)
);

CREATE INDEX IF NOT EXISTS resource_claims_owner
ON resource_claims(owner_kind, owner_id);

CREATE TABLE IF NOT EXISTS instrument_sessions (
    session_id TEXT PRIMARY KEY,
    open_operation_id TEXT NOT NULL UNIQUE,
    actor TEXT NOT NULL,
    config_entry_id TEXT NOT NULL,
    config_content_hash TEXT NOT NULL,
    instrument_ids_json TEXT NOT NULL,
    exclusivity_keys_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('active', 'attention_required', 'closed')
    ),
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attention_reason TEXT,
    active_operation_id TEXT,
    active_operation_kind TEXT CHECK (
        active_operation_kind IS NULL
        OR active_operation_kind IN ('apply', 'invoke', 'collect')
    ),
    end_status TEXT CHECK (
        end_status IS NULL OR end_status IN ('closed', 'aborted')
    ),
    CHECK (
        (
            state = 'active'
            AND attention_reason IS NULL
            AND end_status IS NULL
        )
        OR (
            state = 'attention_required'
            AND attention_reason IS NOT NULL
            AND end_status IS NULL
        )
        OR (
            state = 'closed'
            AND attention_reason IS NULL
            AND active_operation_id IS NULL
            AND active_operation_kind IS NULL
            AND end_status IS NOT NULL
        )
    ),
    CHECK (
        (active_operation_id IS NULL) = (active_operation_kind IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS instrument_sessions_state
ON instrument_sessions(state);
"""  # noqa: S608 - interpolates an internal integer constant

PROJECT_SCHEMA_SQL = "\n".join(
    (
        "BEGIN IMMEDIATE;",
        _CONTROL_TABLES_SQL,
        RUN_TABLES_SQL,
        CONFIG_REGISTRY_TABLES_SQL,
        EXECUTION_TABLES_SQL,
        "COMMIT;",
    )
)
