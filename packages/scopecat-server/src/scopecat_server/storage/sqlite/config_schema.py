"""SQLite configuration-registry tables."""

CONFIG_REGISTRY_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS config_registry_entries (
    entry_id TEXT PRIMARY KEY,
    config_ref TEXT NOT NULL UNIQUE,
    entry_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_registry_activations (
    generation INTEGER PRIMARY KEY CHECK (generation >= 1),
    entry_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY (entry_id)
        REFERENCES config_registry_entries(entry_id)
);

CREATE TABLE IF NOT EXISTS config_activation_operations (
    operation_id TEXT PRIMARY KEY,
    intent_hash TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    expected_generation INTEGER NOT NULL CHECK (expected_generation >= 0),
    activation_generation INTEGER NOT NULL CHECK (activation_generation >= 1),
    operation_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    CHECK (
        activation_generation = expected_generation
        OR activation_generation = expected_generation + 1
    ),
    FOREIGN KEY (entry_id)
        REFERENCES config_registry_entries(entry_id),
    FOREIGN KEY (activation_generation)
        REFERENCES config_registry_activations(generation)
);
"""
