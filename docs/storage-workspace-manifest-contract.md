# Storage Workspace And Manifest Contract

Status: accepted design baseline
Date: 2026-06-27

This note records the storage and manifest decisions that are upstream of
measurement storage backends, large plan previews, reports, comparisons,
candidate configs, analysis artifacts, and future domain-package assets.

Scopecat remains local-first. The durable contract is the typed record graph,
run-relative refs, and artifact identity rules. The exact local directory
layout stays private behind storage APIs unless this note names it as durable.

## Current Baseline

The current implementation has these stable pieces:

- `RunManifest` is the root record for a run.
- `manifest.json`, `config-profile.snapshot.json`, `plan.snapshot.json`, and
  `events.jsonl` are canonical run-level records.
- `artifact_refs` is the generic artifact index on `RunManifest`.
- Dedicated manifest ref lists still exist for some lower-level workflow
  records. Measurement datasets have already moved to artifact discovery.
- `Artifact` records carry `id`, `kind`, run-relative `path`, optional media
  type, and metadata.
- `ArtifactRef` is available for content-addressed or external assets used by
  specs, managed instruments, and future domain packages.
- `LocalRunStore` and `LocalRunLayout` are private implementation details.

This is enough for the accepted architecture, but it is not yet strong enough
for large preview tables, multiple measurement backends, or extracted domain
packages. Those features need a single rule for how records discover each
other.

## Durable Contract

The durable workspace contract is:

- A workspace contains runs, registry state, imported source artifacts, and
  domain-package assets, but only run manifests and typed records are stable
  public data.
- A run is identified by `run_id` and rooted by one `RunManifest`.
- Every stored ref inside a run is a normalized POSIX path relative to that run
  root. Absolute paths and parent-directory escapes are invalid.
- Run-level records have stable semantic refs:
  - `manifest.json`
  - `config-profile.snapshot.json`
  - `plan.snapshot.json`
  - `events.jsonl`
- Large or optional records are discovered through typed `Artifact` entries in
  `RunManifest.artifact_refs`.
- `Artifact.id` is the stable selector for user and record cross-references.
  `Artifact.path` is the storage locator. Both may resolve an artifact, but
  new durable records should prefer artifact ids for cross-reference fields.
- Artifact refs may point at files under `artifacts/`, but the `artifacts/`
  directory name is local layout, not a semantic category.
- External or content-addressed assets use `ArtifactRef`, not run-relative
  `Artifact`, until they are materialized into a run.

The non-contract implementation details are:

- the concrete workspace root directory name used by a caller;
- the `runs/` directory name;
- the private `LocalRunLayout` and `LocalRunStore` class names;
- file grouping under `artifacts/`;
- atomic-write temporary filenames;
- test-helper or local display paths.

## Manifest Indexing

`RunManifest.artifact_refs` remains the canonical artifact index. Measurement
datasets are now discovered through typed artifacts instead of the former
`measurement_dataset_refs` list. Remaining dedicated workflow record lists
should be converged into typed artifact indexes when their internal record
families are retired.

Accepted direction:

- Keep `artifact_refs` as the complete index of non-root run artifacts.
- Treat dedicated lower-level workflow ref lists as cleanup debt inside the
  local codebase, not as a pattern to extend.
- Do not add new top-level manifest lists for preview tables, reports,
  comparisons, calibration outputs, chunk manifests, or domain assets.
- Add typed artifact metadata only when filtering by `kind` is insufficient.
- Keep manifest indexes shallow. The manifest should identify artifacts; the
  artifact payload owns detailed schema, provenance, and nested refs.

The measurement dataset cleanup has already removed the dedicated measurement
list. Remaining workflow record lists imply a future breaking cleanup:

- introduce manifest access helpers that query artifacts by id, kind, and
  metadata;
- migrate workflow records to refer to artifact ids where possible;
- remove dedicated top-level ref lists after call sites use typed artifact
  discovery;
- keep `RunManifest` focused on run identity, root refs, status, events, and
  artifact discovery.

## Cross-Reference Rules

Durable records should cross-reference each other with the smallest stable
identifier that can be resolved from the manifest graph.

Use these rules:

- Use `run_id` when crossing run boundaries.
- Use `Artifact.id` when referring to another artifact in the same run.
- Use an artifact path only at storage API boundaries or when reporting a
  human-readable location.
- Use `ArtifactRef` for assets that are outside the current run or not yet
  materialized into local run storage.
- Store source artifact ids in payload provenance when a derived record depends
  on another artifact.
- Store both artifact ids and typed payload fields when a workflow record needs
  auditability. Do not rely on filename conventions to recover semantics.
- Keep `point_id`, `plan_content_hash`, and schema versions in payload records
  when they are needed to prove that an artifact belongs to the planned run.

Specific record-family direction:

- Lower-level automation jobs should list input and output artifact ids in
  their typed records. The manifest indexes the job record and outputs as
  artifacts.
- Candidate review, finalization, and activation records should refer to
  candidate config, review, activation, and internal proposal artifacts by
  artifact id, plus domain-specific ids such as registry entry id when needed.
- Run comparisons should cross runs with `run_id` and cross artifacts with
  artifact ids, not embedded paths.
- Reports should store section-level refs as artifact ids and let the manifest
  resolve those refs to paths and media types.
- Boundary records around native execution, runner adapters, scheduling,
  recovery, and resume should keep plan identity fields in the payload and use
  artifact ids for status, summary, and data artifacts.

## Storage API Direction

Public workflow code should not depend on local layout classes. The storage API
boundary should expose typed operations:

- open a workspace;
- list runs;
- read/write root run records;
- add or replace manifest artifacts;
- resolve an artifact selector by id or path;
- read typed JSON, JSONL, text, table, array, and binary artifacts;
- validate a run-relative ref without exposing layout internals.

The local backend can continue to implement these operations with ordinary
files. Future backends may use object storage, content-addressed storage, or
columnar stores as long as the same typed refs and artifact records are
preserved.

## Implications For Next Design Notes

Measurement storage backends:

- `MeasurementDataset` remains a row-facing contract until a measurement
  backend note decides otherwise.
- Table, array, chunk, and scalar-row outputs should all be artifacts indexed
  by the manifest.
- Chunk manifests should be artifacts with typed payloads, not new top-level
  manifest lists.

`PlanSnapshot` preview storage:

- Inline previews remain part of `PlanSnapshot` for small plans.
- Large point, parameter-patch, and state previews should become artifacts
  referenced from `PlanSnapshot` by artifact id.
- Preview artifact schemas belong to the preview-storage design note; this
  note only fixes their discovery path.

Domain package extraction:

- Domain package assets should use `ArtifactRef` before run materialization.
- Domain-owned run outputs should become ordinary manifest artifacts with
  domain-specific `kind` values and typed payload schemas.
- Extracted packages must not rely on local `runs/` or `artifacts/` names.

## Accepted Decisions

- The durable storage graph is manifest plus typed artifacts, not filesystem
  layout.
- Run-relative refs are normalized POSIX paths and cannot escape the run root.
- `artifact_refs` is the canonical artifact index.
- New durable records should cross-reference artifacts by artifact id.
- Dedicated top-level manifest ref lists are not a pattern for new work.
- Local storage classes remain private implementation details.
- Future implementation should clean dedicated ref lists after adding manifest
  query helpers.

## Deferred Questions

- Whether `RunManifest` should receive a schema-version bump when dedicated ref
  lists are removed.
- Whether artifact ids need globally namespaced prefixes by record family.
- Whether workspace-level registries need a typed manifest similar to
  `RunManifest`.
- Whether content-addressed artifacts should be first-class in the local
  backend or remain `ArtifactRef` metadata until needed.
- Whether user-facing artifact selectors should allow paths indefinitely or
  move to id-only selection after migration.
