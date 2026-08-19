"""SQLite durable one-shot procedure schedule table."""

PROCEDURE_SCHEDULE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS procedure_schedules (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id TEXT NOT NULL UNIQUE,
    intent_hash TEXT NOT NULL,
    due_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'materialized', 'cancelled')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    procedure_run_id TEXT UNIQUE
        REFERENCES procedure_runs(procedure_run_id),
    schedule_json TEXT NOT NULL,
    CHECK (
        (state = 'materialized' AND procedure_run_id IS NOT NULL)
        OR (state <> 'materialized' AND procedure_run_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS procedure_schedules_state_due_sequence
ON procedure_schedules(state, due_at, sequence);

CREATE INDEX IF NOT EXISTS procedure_schedules_state_sequence
ON procedure_schedules(state, sequence);
"""


__all__ = ["PROCEDURE_SCHEDULE_TABLES_SQL"]
