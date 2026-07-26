"""SQLite run-index tables."""

RUN_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS run_repository_refs (
    run_id TEXT NOT NULL,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (run_id, ref)
);
"""
