"""SQLite run-index tables."""

RUN_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS run_repository_refs (
    run_id TEXT NOT NULL,
    ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    size INTEGER NOT NULL CHECK (size >= 0),
    PRIMARY KEY (run_id, ref)
);

CREATE INDEX IF NOT EXISTS run_repository_refs_digest
ON run_repository_refs(digest);

CREATE TABLE IF NOT EXISTS run_repository_manifests (
    run_id TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS run_repository_manifests_created
ON run_repository_manifests(created_at, run_id);
"""
