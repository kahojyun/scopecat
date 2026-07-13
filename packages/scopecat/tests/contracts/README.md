# Contract Tests

Contract tests cover boundaries that private integrations, brownfield
integration code, or durable workspace records must be able to trust while
internals move.

Current scope:

- Authoring/execution projections: exact golden JSON emitted from the canonical
  simple-scan DSL/config by the real compiler pipeline for `RunRequest` v4 and
  `RunPlanRecord` v3, including corruption rejection, independent persisted
  reads, and the exclusion of transient compiler identity.
- ConfigRegistry records: entry, index, registration job, config snapshots,
  activation records, active state, and provenance persistence.
- Importer boundary records: typed `ParameterImportResult` output, source
  provenance, problems, imported parameter drafts/snapshots, and linked
  artifacts.
- Execution boundary records: execution boundary manifests, including
  plan hashes, result refs, problems, and persisted run artifacts. These
  assertions live with the execution workflow tests because the durable record
  is coupled to run finalization.
- Workflow boundary records: run-comparison jobs/results/reviews, parameter
  change decision records, and structured overview inputs. These tests should
  assert serialized durable shape and typed input/output records, not private
  helper placement.

Keep implementation details in ordinary unit or integration tests. Do not add
contract tests for full storage layouts, Markdown wording, or derived artifact
snapshots unless that artifact is itself a boundary record.
