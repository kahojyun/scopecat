"""Current SQLite project-store schema."""

from scopecat.adapters.sqlite.config_schema import CONFIG_REGISTRY_TABLES_SQL
from scopecat.adapters.sqlite.execution_schema import EXECUTION_TABLES_SQL
from scopecat.adapters.sqlite.run_schema import RUN_TABLES_SQL

PROJECT_SCHEMA_VERSION = 10

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
    CHECK (
        (state = 'attention_required' AND attention_reason IS NOT NULL)
        OR (state <> 'attention_required' AND attention_reason IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS scheduler_runs_state_sequence
ON scheduler_runs(state, sequence);

CREATE TABLE IF NOT EXISTS run_resource_requirements (
    run_id TEXT NOT NULL REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    PRIMARY KEY (run_id, resource_kind, resource_id)
);

CREATE TABLE IF NOT EXISTS durable_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS durable_events_run_id_event_id
ON durable_events(run_id, event_id);

CREATE TABLE IF NOT EXISTS executor_leases (
    run_id TEXT PRIMARY KEY REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    executor_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_leases (
    resource_kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    executor_token TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'quarantined')),
    acquired_at TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (resource_kind, resource_id),
    CHECK (
        (
            status = 'active'
            AND executor_token IS NOT NULL
            AND expires_at IS NOT NULL
        )
        OR (
            status = 'quarantined'
            AND executor_token IS NULL
            AND expires_at IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS resource_leases_run_id ON resource_leases(run_id);
"""  # noqa: S608 - interpolates an internal integer constant.

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
