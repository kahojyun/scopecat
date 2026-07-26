"""SQLite configuration-registry tables."""

CONFIG_REGISTRY_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS config_registry_entries (
    entry_id TEXT PRIMARY KEY,
    config_ref TEXT NOT NULL UNIQUE,
    entry_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_registry_activations (
    generation INTEGER PRIMARY KEY CHECK (generation >= 1),
    record_id TEXT NOT NULL UNIQUE,
    entry_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY (entry_id)
        REFERENCES config_registry_entries(entry_id)
);
"""
