"""SQLite schema for the workspace configuration registry."""

CONFIG_REGISTRY_SCHEMA_VERSION = 1

CONFIG_REGISTRY_SCHEMA_SQL = """
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS config_registry_schema (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL
);

INSERT OR IGNORE INTO config_registry_schema(singleton, version) VALUES (1, 1);

CREATE TABLE IF NOT EXISTS config_registry_entries (
    entry_id TEXT PRIMARY KEY,
    config_ref TEXT NOT NULL UNIQUE,
    entry_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_registry_index (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    index_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_registry_active (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    active_entry_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    FOREIGN KEY (active_entry_id)
        REFERENCES config_registry_entries(entry_id)
);

CREATE TABLE IF NOT EXISTS config_registry_activations (
    generation INTEGER PRIMARY KEY CHECK (generation >= 1),
    record_id TEXT NOT NULL UNIQUE,
    entry_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY (entry_id)
        REFERENCES config_registry_entries(entry_id)
);

COMMIT;
"""
