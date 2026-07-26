"""SQLite execution-index tables."""

EXECUTION_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS execution_measurement_appends (
    run_id TEXT NOT NULL,
    start_index INTEGER NOT NULL CHECK (start_index >= 0),
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    contract_fingerprint TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count > 0),
    ref TEXT NOT NULL,
    PRIMARY KEY (run_id, start_index),
    UNIQUE (run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_measurement_seals (
    run_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dataset_content_hash TEXT NOT NULL,
    UNIQUE (run_id, operation_id)
);

"""
