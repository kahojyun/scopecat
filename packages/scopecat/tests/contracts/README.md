# Contract Tests

Contract tests cover boundaries that private integrations, brownfield
integration code, or durable workspace records must be able to trust while
internals move.

Current scope:

- Authoring/execution projections: exact golden JSON emitted from the canonical
  simple-scan DSL/config by the real compiler pipeline for `RunRequest` v4 and
  `RunPlanRecord` v7, including corruption rejection, independent persisted
  reads, and the exclusion of transient compiler identity.
- ConfigRegistry records: entry, index, registration job, config snapshots,
  activation records, active state, and provenance persistence.
- Importer boundary records: typed `ParameterImportResult` output, source
  provenance, problems, imported parameter drafts/snapshots, and linked
  artifacts.
- Execution boundary records: execution boundary manifests, including
  plan hashes, result refs, problems, and persisted run artifacts. These
  assertions live with the run-finalization tests because the durable record
  is coupled to run finalization.
- Collection repositories: shared memory/filesystem behavior for idempotent
  commit, detached resolve results, exact receipt identity and content hashes,
  forged receipt rejection, and conflicting writes. Filesystem storage
  additionally tests malformed persisted bytes at its adapter boundary.
- Execution-side ports: reusable memory/filesystem contracts for journal
  sequencing, measurement-record idempotency and conflict rejection, and
  payload-evidence idempotency and conflict rejection. Adapter-specific
  filesystem durability remains in adapter tests.
- Workspace persistence ports: reusable memory/filesystem contracts for logical
  run refs, atomic if-absent publication, registry registration and generation
  CAS, and mutually exclusive resource leases.
- Import direction: core stays domain-neutral, extension production code uses
  only public Scopecat modules, records/authoring/compiler sublayers point
  inward, application use cases do not select composition or adapters, and
  concrete filesystem adapters are imported only by their composition roots.
- Application boundary records: run-comparison jobs/results/reviews, parameter
  change decision records, and structured overview inputs. These tests should
  assert serialized durable shape and typed input/output records, not private
  helper placement.

Keep implementation details in ordinary unit or integration tests. Do not add
contract tests for full storage layouts, Markdown wording, or derived artifact
snapshots unless that artifact is itself a boundary record.
