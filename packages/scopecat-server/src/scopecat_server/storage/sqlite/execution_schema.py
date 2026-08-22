"""SQLite execution-index tables."""

EXECUTION_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS execution_coverage (
    run_id TEXT PRIMARY KEY REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    completed_point_count INTEGER NOT NULL CHECK (completed_point_count >= 0)
);

CREATE TABLE IF NOT EXISTS execution_domain_job_transitions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    logical_compute_node_id TEXT NOT NULL,
    execution_key TEXT NOT NULL,
    transition_kind TEXT NOT NULL CHECK (
        transition_kind IN ('invocation', 'checkpoint', 'terminal')
    ),
    job_id TEXT,
    revision INTEGER,
    point_ordinals_json TEXT NOT NULL,
    transition_json TEXT NOT NULL,
    CHECK (
        (
            transition_kind = 'checkpoint'
            AND job_id IS NOT NULL
            AND revision IS NOT NULL
            AND revision >= 1
        ) OR (
            transition_kind IN ('invocation', 'terminal')
            AND job_id IS NULL
            AND revision IS NULL
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS execution_domain_job_checkpoint_identity
ON execution_domain_job_transitions(run_id, execution_key, revision)
WHERE transition_kind = 'checkpoint';

CREATE UNIQUE INDEX IF NOT EXISTS execution_domain_job_invocation_identity
ON execution_domain_job_transitions(run_id, execution_key)
WHERE transition_kind = 'invocation';

CREATE UNIQUE INDEX IF NOT EXISTS execution_domain_job_terminal_identity
ON execution_domain_job_transitions(run_id, execution_key)
WHERE transition_kind = 'terminal';

CREATE INDEX IF NOT EXISTS execution_domain_job_transitions_run_sequence
ON execution_domain_job_transitions(run_id, sequence);

CREATE TABLE IF NOT EXISTS execution_point_plans (
    run_id TEXT PRIMARY KEY REFERENCES scheduler_runs(run_id) ON DELETE CASCADE,
    initialize_operation_id TEXT NOT NULL,
    initial_point_count INTEGER NOT NULL CHECK (initial_point_count >= 0),
    accepted_point_count INTEGER NOT NULL CHECK (accepted_point_count >= 0),
    point_limit INTEGER NOT NULL CHECK (point_limit >= 0),
    plan_closed INTEGER NOT NULL CHECK (plan_closed IN (0, 1)),
    stop_operation_id TEXT,
    stop_reason TEXT,
    CHECK (
        initial_point_count <= accepted_point_count
        AND accepted_point_count <= point_limit
    ),
    CHECK (
        (plan_closed = 1 AND stop_operation_id IS NOT NULL AND stop_reason IS NOT NULL)
        OR (plan_closed = 0 AND stop_operation_id IS NULL AND stop_reason IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS execution_domain_decisions (
    run_id TEXT NOT NULL REFERENCES execution_point_plans(run_id) ON DELETE CASCADE,
    proposal_index INTEGER NOT NULL CHECK (proposal_index >= 0),
    operation_id TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    PRIMARY KEY (run_id, proposal_index),
    UNIQUE (run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_domain_queue (
    run_id TEXT NOT NULL REFERENCES execution_point_plans(run_id) ON DELETE CASCADE,
    queue_index INTEGER NOT NULL CHECK (queue_index >= 0),
    request_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'accepted', 'rejected', 'cancelled')
    ),
    decision_operation_id TEXT,
    entry_json TEXT NOT NULL,
    PRIMARY KEY (run_id, queue_index),
    UNIQUE (run_id, request_id),
    FOREIGN KEY (run_id, decision_operation_id)
        REFERENCES execution_domain_decisions(run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_run_points (
    run_id TEXT NOT NULL REFERENCES execution_point_plans(run_id) ON DELETE CASCADE,
    point_index INTEGER NOT NULL CHECK (point_index >= 0),
    decision_operation_id TEXT NOT NULL,
    point_json TEXT NOT NULL,
    PRIMARY KEY (run_id, point_index),
    FOREIGN KEY (run_id, decision_operation_id)
        REFERENCES execution_domain_decisions(run_id, operation_id)
);

CREATE TABLE IF NOT EXISTS execution_measurement_headers (
    run_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    contract_fingerprint TEXT NOT NULL,
    expected_record_count INTEGER CHECK (expected_record_count >= 0),
    record_count_limit INTEGER NOT NULL CHECK (record_count_limit >= 0),
    ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_measurement_fragments (
    segment_id TEXT PRIMARY KEY
        REFERENCES run_execution_segments(segment_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    header_content_hash TEXT NOT NULL,
    start_index INTEGER NOT NULL CHECK (start_index >= 0),
    FOREIGN KEY (run_id) REFERENCES execution_measurement_headers(run_id)
);

CREATE INDEX IF NOT EXISTS execution_measurement_fragments_run_start
ON execution_measurement_fragments(run_id, start_index);

CREATE TABLE IF NOT EXISTS execution_measurement_appends (
    run_id TEXT NOT NULL,
    segment_id TEXT NOT NULL
        REFERENCES execution_measurement_fragments(segment_id),
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
    segment_id TEXT NOT NULL
        REFERENCES execution_measurement_fragments(segment_id),
    operation_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dataset_content_hash TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES execution_measurement_headers(run_id),
    UNIQUE (run_id, operation_id)
);

"""
