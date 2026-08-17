"""SQLite project-analysis publication tables."""

ANALYSIS_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS analysis_publications (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    analysis_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    publication_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    step_id TEXT,
    input_count INTEGER NOT NULL CHECK (input_count >= 0),
    output_count INTEGER NOT NULL CHECK (output_count >= 0),
    manifest_json TEXT NOT NULL,
    UNIQUE (analysis_key, revision)
);

CREATE INDEX IF NOT EXISTS analysis_publications_key_revision
ON analysis_publications(analysis_key, revision DESC);

CREATE TABLE IF NOT EXISTS analysis_repository_refs (
    record_id TEXT NOT NULL REFERENCES analysis_publications(record_id)
        ON DELETE CASCADE,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (record_id, ref)
);
"""
