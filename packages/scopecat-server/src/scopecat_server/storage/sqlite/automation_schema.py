"""SQLite durable procedure-run and worker-lease tables."""

AUTOMATION_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS procedure_runs (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure_run_id TEXT NOT NULL UNIQUE,
    definition_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    intent_hash TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state TEXT NOT NULL CHECK (
        state IN ('ready', 'leased', 'waiting', 'attention_required', 'closed')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    run_json TEXT NOT NULL,
    UNIQUE (definition_id, request_key)
);

CREATE INDEX IF NOT EXISTS procedure_runs_state_sequence
ON procedure_runs(state, sequence);

CREATE TABLE IF NOT EXISTS procedure_step_attempts (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure_run_id TEXT NOT NULL
        REFERENCES procedure_runs(procedure_run_id) ON DELETE CASCADE,
    step_key TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    operation TEXT NOT NULL CHECK (
        operation IN ('run', 'analysis', 'config_activation')
    ),
    intent_hash TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state TEXT NOT NULL CHECK (
        state IN ('running', 'succeeded', 'failed', 'attention_required')
    ),
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    attempt_json TEXT NOT NULL,
    UNIQUE (procedure_run_id, step_key, attempt)
);

CREATE INDEX IF NOT EXISTS procedure_step_attempts_run_step_attempt
ON procedure_step_attempts(procedure_run_id, step_key, attempt DESC);

CREATE UNIQUE INDEX IF NOT EXISTS procedure_step_attempts_one_running
ON procedure_step_attempts(procedure_run_id)
WHERE state = 'running';

CREATE TABLE IF NOT EXISTS procedure_leases (
    procedure_run_id TEXT PRIMARY KEY
        REFERENCES procedure_runs(procedure_run_id) ON DELETE CASCADE,
    worker_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


__all__ = ["AUTOMATION_TABLES_SQL"]
