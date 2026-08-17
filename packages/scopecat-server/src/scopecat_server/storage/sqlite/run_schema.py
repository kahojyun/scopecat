"""SQLite run-index tables."""

RUN_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS run_repository_refs (
    run_id TEXT NOT NULL,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, ref)
);

CREATE TABLE IF NOT EXISTS analysis_publications (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    analysis_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    publication_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    UNIQUE (analysis_key, revision)
);

CREATE INDEX IF NOT EXISTS analysis_publications_key_sequence
ON analysis_publications(analysis_key, sequence);

CREATE TABLE IF NOT EXISTS analysis_repository_refs (
    record_id TEXT NOT NULL REFERENCES analysis_publications(record_id)
        ON DELETE CASCADE,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (record_id, ref)
);
"""
