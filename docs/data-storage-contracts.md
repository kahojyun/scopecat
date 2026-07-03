# Data And Storage Contracts

Status: target design

Scopecat is local-first, but its durable contract is not the local directory
layout. The durable contract is the typed record graph rooted at a
`RunManifest`, stable ids, immutable refs, content hashes, schemas,
provenance, and diagnostics.

## Run Record Graph

A run is identified by one `run_id` and rooted by one `RunManifest`.

Stable run-level records include:

- run manifest;
- config snapshot refs;
- run request refs;
- closed experiment spec refs for structured segments;
- experiment plan refs and preview refs;
- optional device-program refs;
- events;
- result artifacts;
- analysis artifacts;
- candidate config refs;
- comparison and review records;
- attachments and legacy capture artifacts.

The manifest indexes artifacts. Artifact payloads own detailed schemas,
provenance, nested refs, and validation metadata.

`Artifact.id` is the stable user and record selector. `Artifact.path` is a
storage locator. Cross-record references should use the smallest stable id:

- `run_id` across runs;
- `Artifact.id` inside a run;
- `ArtifactRef` for content-addressed or external assets;
- normalized run-relative paths only at storage API boundaries.

Absolute paths and parent-directory escapes are invalid in durable run refs.
Local workspace directory names, temporary filenames, helper classes, and test
display paths are not contract.

## Immutable Refs And Hashes

Closed structured records may be stored as a semantic aggregate with immutable
parts:

```text
ExperimentSpec
  config_snapshot_ref/hash
  run_request_ref/hash
  module_fingerprint_refs
  points_or_point_source_ref/hash
  params_ref/hash
  state_ref/hash
  records_ref/hash
  assets_ref/hash
```

The aggregate content hash must cover every referenced part. If a record can
be recomputed, the inputs, compiler id/version, schema version, diagnostics,
and provenance required to recompute it must be recorded.

Hash canonicalization must be stable for object ordering, units, numeric
values, refs, schema versions, compiler ids, and omitted/default fields.

## Point Records

Structured runs use three identities:

```text
point_index
point_uid
execution_index
```

`point_index` is dense within a segment. `point_uid` is logical identity.
`execution_index` is runtime order and may change across randomized runs,
retries, backend batches, or hardware-offloaded execution.

Static point tables may be inline for small plans or artifact-backed for large
plans. Streaming or adaptive runs record a `PointSourceSpec` plus append-only
`PointDecisionRecord`s. Early stop, retry, partial failure, and skipped points
must not compact or renumber the point table.

## Records And Result Contracts

Measurement semantics live in `RecordSpec`, `ResultContract`, and typed
payload schemas, not in file extensions or backend libraries.

Record roles include:

- coordinate;
- observable;
- auxiliary;
- diagnostic;
- status or mask when represented as data variables.

Record sources include:

- instrument product;
- instrument field/readback;
- expression;
- artifact;
- point column;
- backend-decoded result.

The result contract defines layouts, primary indices, dimensions, dtype, unit,
shape policy, artifact strategy, and validation rules.

Default shape policy is conservative:

- fixed shape may use dense table or array layouts;
- shape-changing controls are errors unless policy is declared;
- `pad_to_max` is allowed only when padding value and validity mask are
  declared;
- `ragged_rows` or append-only rows handle variable shots, repeats, retries,
  early stop, and streaming;
- large blobs and backend-native payloads use artifact refs;
- `split_segments` is preferred when a shape change would otherwise make one
  segment hard to validate.

## Storage Backends

JSONL and JSON are acceptable small-data baselines. Parquet, Arrow, Zarr,
NetCDF, HDF5, NeXus, object storage, and content-addressed storage may appear
behind typed readers and writers when they remove real friction.

No backend library is part of the durable Scopecat contract. The contract is
the artifact kind, schema record, provenance, diagnostics, and typed reader
behavior.

## Plans And Device Programs

`ExperimentPlan` is the root execution contract for a closed spec. It contains
or references point previews, point-local patches, desired logical state,
record materialization, result contracts, diagnostics, compiler metadata, and
artifact refs.

`DeviceProgram` is the device-aware command plan. It may include:

- group-level command slices;
- physical-instrument command slices;
- state patches;
- uploads;
- arm, trigger, acquire, readback, cleanup, and abort commands;
- point/group/backend mapping;
- sync and barrier metadata;
- resource lease metadata;
- capability validation diagnostics.

Plans and device programs may be cached or recomputed. If persisted, they must
record compiler id/version and every input hash needed to decide whether the
record is still valid.

## Provenance

Every persisted measurement, result artifact, program artifact, analysis
artifact, candidate patch, or derived view should carry enough provenance to
audit:

- source run id;
- schema version;
- artifact id and kind;
- record ids and result contract id when point-scoped;
- experiment spec hash and plan hash when applicable;
- point identity below whole-run scope;
- config snapshot hash and candidate source when relevant;
- compiler, code island, adapter, or analysis step id/version/fingerprint;
- source artifact ids for derived data;
- units, dimensions, variable roles, masks, statuses, and diagnostics through
  schema or payload;
- determinism level and seed/rng state when relevant.

Auditable provenance is acceptable for early code islands. Reproducibility
claims require stronger evidence: deterministic inputs, dependency versions,
fingerprints, seeds, and absence of hidden side effects.

## Legacy Capture

`RunScope` records legacy execution evidence under the same run graph. It may
capture inputs, config files, generated artifacts, events, measurement outputs,
notes, analysis, and provenance level.

Capture records must be labeled as capture. They should not pretend to have a
closed `ExperimentSpec`, `ExperimentPlan`, or `DeviceProgram` unless those
records were actually produced.

## Calibration Evidence

Accepted calibration values are accepted parameter/config values inside a
`ConfigSnapshot`. Do not introduce a second accepted-state root for values that
can be represented as parameter scalars, parameter table rows, routing entries,
or config sections.

Fit outputs, model results, covariance, residuals, classifier thresholds,
quality metrics, figures, and rejected candidates are analysis or workflow
artifacts until review policy chooses config patches.

Calibration provenance should be reconstructable from source run manifests,
experiment specs, plans, result artifacts, analysis artifacts, parameter change
sets, candidate snapshots, review decisions, activation records, follow-up
runs, comparisons, and structured overviews.

## Diagnostics

Diagnostics are durable boundary behavior. Planning, storage, analysis,
runtime, and instrument-provider APIs should report stable diagnostic codes and
logical locations instead of raw exceptions or local file paths.

Important diagnostic families include:

- relation and parameter lookup failures;
- config/schema mismatch and unknown refs;
- unit mismatch and safety-bound violations;
- invalid point identity or point-source state;
- invalid sweep composition or override precedence;
- unsupported record source or payload shape;
- missing, duplicate, incomplete, or ineligible artifacts;
- chunk gaps, duplicate chunks, or invalid finalization;
- stale candidate expected values and activation invalidation;
- backend, runtime, instrument-provider, and unsupported-operation failures.

A generated diagnostics catalog is preferable to a hand-maintained docs table.
`docs/` preserves diagnostic policy, not every code.
