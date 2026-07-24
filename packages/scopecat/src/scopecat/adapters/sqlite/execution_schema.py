"""Current SQLite execution-index schema."""

EXECUTION_SCHEMA_VERSION = 2

EXECUTION_SCHEMA_SQL = """
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS execution_repository_schema (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL
);

INSERT OR IGNORE INTO execution_repository_schema(singleton, version)
VALUES (1, 2);

CREATE TABLE IF NOT EXISTS execution_journal_entries (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    UNIQUE (run_id, ref)
);

CREATE TABLE IF NOT EXISTS execution_journal_batches (
    run_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_sequence INTEGER NOT NULL CHECK (first_sequence >= 0),
    transition_count INTEGER NOT NULL CHECK (transition_count > 0),
    PRIMARY KEY (run_id, batch_id)
);

CREATE TABLE IF NOT EXISTS execution_measurement_appends (
    run_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    start_index INTEGER NOT NULL CHECK (start_index >= 0),
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    contract_fingerprint TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count > 0),
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, dataset_id, start_index),
    UNIQUE (run_id, operation_id)
);

CREATE INDEX IF NOT EXISTS execution_measurement_appends_run
ON execution_measurement_appends(run_id, dataset_id, start_index);

CREATE TABLE IF NOT EXISTS execution_measurement_seals (
    run_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dataset_content_hash TEXT NOT NULL,
    contract_fingerprint TEXT NOT NULL,
    point_count INTEGER NOT NULL CHECK (point_count >= 0),
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, dataset_id),
    UNIQUE (run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_collections (
    run_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_payload_evidence (
    run_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, operation_id)
);

COMMIT;
"""
