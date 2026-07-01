# Contract Tests

Contract tests cover boundaries that private adapters, brownfield integration
code, or durable workspace records must be able to trust while internals move.

Current scope:

- Runner Adapter SDK: typed context, measurement recording, adapter-owned
  artifacts, and failed-run persistence.
- ConfigRegistry records: entry, index, registration job, config snapshots,
  activation records, active state, and provenance persistence.
- Importer boundary records: typed `ParameterImportResult` output, source
  provenance, diagnostics, imported parameter state, and linked artifacts.
- Execution boundary records: native execution and runner-adapter boundary
  manifests, including plan hashes, result refs, diagnostics, and persisted
  run artifacts. These assertions live with the execution workflow tests because
  the durable record is coupled to run finalization.
- Workflow boundary records: scheduling plans, resume manifests, retry reports,
  run-comparison jobs/results/reviews, parameter change decision records, and
  structured overview inputs. These tests should assert serialized durable
  shape and typed input/output records, not private helper placement.

Keep implementation details in ordinary unit or integration tests. Do not add
contract tests for full storage layouts, Markdown wording, or derived artifact
snapshots unless that artifact is itself a boundary record.
