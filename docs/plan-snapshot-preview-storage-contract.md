# PlanSnapshot Preview Storage Contract

Status: accepted design baseline
Date: 2026-06-27

This note records the `PlanSnapshot` preview-storage decisions that build on
[Storage Workspace And Manifest Contract](storage-workspace-manifest-contract.md)
and
[Measurement Storage Backends Contract](measurement-storage-backends-contract.md).
It defines when planning output remains inline and when dry-run/review previews
move into artifact-backed tables.

The goal is to keep the plan root small enough to load cheaply while preserving
reviewability for large point, parameter-patch, desired-state, and state-patch
tables.

## Current Baseline

`PlanSnapshot` v1 is the durable aggregate produced by `plan_experiment`.
It currently stores these preview-like collections inline:

- `points: list[PointRecord]`
- `parameter_patches: list[ParameterPatchPlanRecord]`
- `desired_state: list[StateRecord]`
- `state_patches: list[StatePatchRecord]`
- `result_intents: list[ResultIntent]`
- `expected_dataset_schema`
- diagnostics, hashes, acquisition, and asset refs

This is acceptable for the current examples and tests. It is not the target
shape for large plans because relation expansion, repeated desired-state
bindings, and point-local parameter table patches can grow far faster than the
root plan metadata.

## Durable Contract

The durable planning contract is:

- `PlanSnapshot` remains the root record for plan identity, hashes,
  diagnostics, acquisition shape, result intents, expected measurement schema,
  and preview discovery.
- Small plans may keep complete point, patch, desired-state, and state-patch
  previews inline.
- Large plans should store preview rows as manifest artifacts and keep only
  summary metadata plus artifact ids in `PlanSnapshot`.
- Preview artifacts are planner artifacts, not measurement artifacts. They may
  reuse table storage mechanics, but their schemas belong to planning.
- Preview artifacts are user-facing contracts for dry-run review, notebooks,
  reports, and adapter boundary diagnostics once introduced.
- Execution paths should consume stable plan identity and point ids from
  `PlanSnapshot`, not depend on preview artifact file layout.

## Inline Limits

The next implementation should enforce an explicit inline budget. The accepted
default budget is:

- at most 200 inline point rows;
- at most 2,000 inline parameter-patch records;
- at most 2,000 inline desired-state records;
- at most 2,000 inline state-patch records;
- at most 5 MiB serialized `plan.snapshot.json`.

When any budget is exceeded, the planner should:

- keep root plan metadata, hashes, counts, and diagnostics inline;
- store the oversized section as one or more preview artifacts;
- record the artifact id, schema version, row count, and truncation status in a
  preview index on `PlanSnapshot`;
- keep a small inline sample only if it is explicitly marked as truncated.

These limits are product defaults, not storage backend limits. They can become
planner options later, but the persisted snapshot must record the effective
limits used for the run.

## Preview Index

The next `PlanSnapshot` schema should add a preview index rather than adding
another top-level `RunManifest` ref list.

The index should contain one entry per preview artifact:

- preview kind;
- artifact id;
- artifact schema version;
- row count;
- inline sample count;
- whether inline rows are complete or truncated;
- source plan `content_hash`;
- source section path such as `points` or `parameter_patches`.

Candidate preview kinds:

- `plan_point_preview`
- `plan_parameter_patch_preview`
- `plan_desired_state_preview`
- `plan_state_patch_preview`
- `plan_result_intent_preview`

The manifest remains the artifact discovery index. `PlanSnapshot` stores
artifact ids and preview metadata; `RunManifest.artifact_refs` resolves those
ids to paths, media types, and artifact metadata.

## Artifact Schemas

Preview artifacts should be table-shaped records with stable schema versions.
They may be serialized as JSON initially and later use Parquet or Arrow behind
typed readers.

`plan_point_preview.v1` rows:

- `point_id`
- point row values, preserving `Quantity` payloads where present
- optional source row hash

`plan_parameter_patch_preview.v1` rows:

- `point_id`
- patch index
- patch kind
- scalar parameter id or table id
- key values for row patches
- patch values or inserted/deleted rows
- affected row sample or affected row artifact id when too large

`plan_desired_state_preview.v1` rows:

- `point_id`
- resource id
- field
- value
- optional source state spec index

`plan_state_patch_preview.v1` rows:

- `point_id`
- resource id
- field
- before value
- after value

`plan_result_intent_preview.v1` rows:

- result intent id
- kind
- unit
- resource
- expected record role or artifact eligibility hint when available

Each preview artifact should include artifact metadata:

- `preview_kind`
- `plan_content_hash`
- `experiment_id`
- `experiment_kind`
- `row_count`
- `source_section`
- `schema_version`

## Diagnostics And Locations

Planning diagnostics should continue to live on `PlanSnapshot`. Diagnostics
that refer to preview rows must be able to point into inline rows or artifact
rows without changing diagnostic codes.

Accepted location format:

- inline row: `points.12.row.frequency`
- artifact row: `preview_refs.points.rows.12.frequency`
- artifact id scoped row:
  `preview_artifacts.plan-points.rows.12.frequency`

The exact internal path helper can evolve, but diagnostics must carry:

- the stable diagnostic code;
- the logical section;
- the row identifier or point id when available;
- the artifact id when the row is not inline.

Do not use local file paths as diagnostic identity. File paths may appear in
debug output, but artifact ids and logical row locations are the durable
contract.

## Relationship To Execution

Preview storage is for review and diagnostics. Execution should not require
opening preview artifacts to determine the durable plan identity.

Execution boundaries may use preview artifacts for:

- adapter-specific debug output;
- dry-run tables;
- human-readable reports;
- large-plan inspection;
- diagnostics that need row context.

Execution boundaries must continue to use:

- `content_hash`
- `point_coordinate_ids`
- point ids;
- acquisition plan;
- expected dataset schema;
- boundary records that summarize point counts and plan hashes.

## Relationship To Future Design Notes

Relation execution scale:

- Large relation outputs should materialize as point preview artifacts when
  they are part of planning review.
- A future relation execution engine must not become the durable preview file
  format. It can only be a backend behind typed preview readers.

Calibration state:

- Calibration proposal previews may reuse plan preview table mechanics, but
  accepted calibration state remains a separate design decision.

Diagnostics catalog:

- Preview storage should stabilize diagnostic families for preview truncation,
  preview artifact missing, preview schema mismatch, and preview row lookup
  failures.

## Accepted Decisions

- `PlanSnapshot` remains the root plan identity record.
- Inline previews are accepted only within explicit budgets.
- Large point, parameter-patch, desired-state, state-patch, and result-intent
  previews should become manifest artifacts.
- Preview artifacts are planner artifacts and user-facing review contracts.
- The next `PlanSnapshot` schema should carry a preview index of artifact ids,
  counts, schema versions, and truncation state.
- Diagnostics should point to logical preview sections and artifact ids, not
  local file paths.
- Relation and table backends are implementation details behind typed preview
  readers.

## Deferred Questions

- Whether the next schema should be `scopecat.plan_snapshot.v2` or a v1
  additive change while the project still has no external compatibility
  contract.
- Exact Pydantic model names for preview index entries and preview artifact
  payloads.
- Whether inline samples should be first, evenly sampled, diagnostic-focused,
  or user-configurable.
- Whether preview artifacts should be emitted during `plan_experiment` or only
  during dry-run persistence when a workspace is available.
- Whether `result_intents` should remain always inline because it is usually
  small.
