"""SQLite sample registry, immutable revisions, and run bindings."""

SAMPLE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS samples (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active_revision INTEGER NOT NULL CHECK (active_revision >= 1),
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_revisions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    content_hash TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    revision_json TEXT NOT NULL,
    UNIQUE (sample_id, revision)
);

CREATE INDEX IF NOT EXISTS sample_revisions_sample_sequence
ON sample_revisions(sample_id, sequence DESC);

CREATE TABLE IF NOT EXISTS sample_mutation_operations (
    operation_id TEXT PRIMARY KEY,
    intent_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_sample_bindings (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    sample_id TEXT NOT NULL REFERENCES samples(sample_id),
    revision INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    context_id TEXT,
    binding_json TEXT NOT NULL,
    PRIMARY KEY (run_id, role),
    UNIQUE (run_id, sample_id),
    FOREIGN KEY (sample_id, revision)
        REFERENCES sample_revisions(sample_id, revision)
);

CREATE INDEX IF NOT EXISTS run_sample_bindings_sample_run
ON run_sample_bindings(sample_id, run_id);
"""

__all__ = ["SAMPLE_TABLES_SQL"]
