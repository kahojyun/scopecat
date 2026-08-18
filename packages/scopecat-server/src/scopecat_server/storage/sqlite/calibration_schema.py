"""SQLite durable calibration-cohort tables."""

CALIBRATION_COHORT_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS calibration_cohorts (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort_id TEXT NOT NULL UNIQUE,
    planner_id TEXT NOT NULL,
    planner_version TEXT NOT NULL,
    planner_fingerprint TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    fanout_scope TEXT NOT NULL,
    member_count INTEGER NOT NULL CHECK (member_count BETWEEN 1 AND 200),
    config_generation INTEGER NOT NULL CHECK (config_generation >= 1),
    evaluated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cohort_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS calibration_cohorts_scope_sequence
ON calibration_cohorts(fanout_scope, sequence DESC);

CREATE TABLE IF NOT EXISTS calibration_cohort_members (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort_id TEXT NOT NULL
        REFERENCES calibration_cohorts(cohort_id) ON DELETE CASCADE,
    member_index INTEGER NOT NULL CHECK (member_index >= 0),
    member_id TEXT NOT NULL,
    calibration_key TEXT NOT NULL,
    procedure_run_id TEXT NOT NULL UNIQUE
        REFERENCES procedure_runs(procedure_run_id) ON DELETE RESTRICT,
    request_key TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    closure_status TEXT CHECK (
        closure_status IS NULL
        OR closure_status IN ('succeeded', 'failed', 'cancelled')
    ),
    closed_at TEXT,
    member_json TEXT NOT NULL,
    UNIQUE (cohort_id, member_index),
    UNIQUE (cohort_id, member_id),
    UNIQUE (cohort_id, calibration_key),
    CHECK (
        (closure_status IS NULL AND closed_at IS NULL)
        OR (closure_status IS NOT NULL AND closed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS calibration_cohort_members_key_sequence
ON calibration_cohort_members(calibration_key, sequence DESC);

CREATE INDEX IF NOT EXISTS calibration_cohort_members_success_key_sequence
ON calibration_cohort_members(calibration_key, sequence DESC)
WHERE closure_status = 'succeeded';

CREATE TRIGGER IF NOT EXISTS calibration_cohort_members_sync_terminal_closure
AFTER UPDATE OF closure_status, closed_at ON procedure_runs
FOR EACH ROW
WHEN NEW.state = 'closed'
BEGIN
    UPDATE calibration_cohort_members
    SET closure_status = NEW.closure_status,
        closed_at = NEW.closed_at
    WHERE procedure_run_id = NEW.procedure_run_id;
END;
"""


__all__ = ["CALIBRATION_COHORT_TABLES_SQL"]
