"""SQLite execution-index tables."""

EXECUTION_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS execution_coverage (
    run_id TEXT PRIMARY KEY REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    completed_point_count INTEGER NOT NULL CHECK (completed_point_count >= 0)
);

CREATE TABLE IF NOT EXISTS execution_measurement_headers (
    run_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    contract_fingerprint TEXT NOT NULL,
    expected_record_count INTEGER NOT NULL CHECK (expected_record_count >= 0),
    ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_measurement_appends (
    run_id TEXT NOT NULL,
    start_index INTEGER NOT NULL CHECK (start_index >= 0),
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    header_content_hash TEXT NOT NULL,
    record_content_hashes_json TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count > 0),
    ref TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES execution_measurement_headers(run_id),
    PRIMARY KEY (run_id, start_index),
    UNIQUE (run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_measurement_seals (
    run_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dataset_content_hash TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES execution_measurement_headers(run_id),
    UNIQUE (run_id, operation_id)
);

"""
