"""Current SQLite run-index schema."""

RUN_SCHEMA_VERSION = 1

RUN_SCHEMA_SQL = """
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS run_repository_schema (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL
);

INSERT OR IGNORE INTO run_repository_schema(singleton, version) VALUES (1, 1);

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

COMMIT;
"""
