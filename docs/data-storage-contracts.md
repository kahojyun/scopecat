# Data And Storage Contracts

Scopecat is local-first, but its durable contract is not the local directory
layout. The durable contract is the typed record graph rooted at a
`RunManifest`, normalized run-relative refs, artifact identity, schemas,
provenance, and diagnostics.

## Workspace Graph

A run is identified by one `run_id` and rooted by one `RunManifest`.

Stable run-level records include:

- `manifest.json`
- `config-profile.snapshot.json`
- `plan.snapshot.json`
- `events.jsonl`

Large, optional, derived, or domain-shaped records are discovered through typed
`Artifact` entries in `RunManifest.artifact_refs`.

`Artifact.id` is the stable selector for user and record cross-references.
`Artifact.path` is the storage locator. New durable records should prefer
artifact ids for cross-reference fields.

Every stored ref inside a run is a normalized POSIX path relative to that run
root. Absolute paths and parent-directory escapes are invalid.

The non-contract details are local workspace directory names, `runs/`,
`artifacts/`, atomic-write temporary filenames, helper class names, and test
display paths.

## Manifest Indexing

`RunManifest.artifact_refs` is the canonical artifact index for non-root run
records.

Do not add new top-level manifest lists for preview tables,
comparisons, calibration outputs, chunk manifests, backend partitions, or
domain assets. The manifest identifies artifacts; the artifact payload owns
detailed schema, provenance, and nested refs.

Durable records should cross-reference each other with the smallest stable
identifier that can be resolved from the manifest graph:

- use `run_id` when crossing run boundaries;
- use `Artifact.id` when referring to another artifact in the same run;
- use `ArtifactRef` for assets outside the current run or not yet materialized
  into local run storage;
- use artifact paths only at storage API boundaries or for human-readable
  debug output.

## Measurement Shapes

Measurement semantics live in schemas and typed payload records, not in file
extensions or backend libraries.

Use scalar row datasets when data is one record per logical point, shot,
repeat, or decoded summary and analysis can consume rows without opening a
richer payload.

Use typed table artifacts when data is sparse or non-orthogonal, or when
columns need roles such as identifier, coordinate, observable, uncertainty,
status, mask, or metadata.

Use typed array artifacts when variables have named dimensions and regular
shapes, such as IQ clouds, spectra, waveforms, images, matrices, dense model
outputs, or aligned uncertainty/status/mask variables.

Use chunk manifests when a table or array is written incrementally and
duplicate, missing, ordered, or final-chunk diagnostics must be auditable.

Use events or workflow records when information describes execution policy,
operator decisions, retries, early stop, resume, or online analysis rather
than measured values.

Do not turn generic metadata fields into untyped catch-all models.

## Provenance

Every persisted measurement or derived artifact should carry enough provenance
to prove:

- source run id;
- schema version;
- dataset or artifact id;
- dataset role or artifact kind;
- plan content hash when point-scoped;
- point identity when scoped below a whole run;
- source adapter or analysis step id;
- source artifact ids for derived data;
- units, dimensions, variable roles, and diagnostics through schema or payload;
- config/profile or parameter-build identity when needed for replay.

Path-style upstream refs are local compatibility debt and should stay at
storage boundaries instead of durable metadata.

## Backend Policy

JSONL and JSON are acceptable small-data baselines. Parquet, Arrow, Zarr,
NetCDF, HDF5, NeXus, object storage, and content-addressed storage may appear
behind typed readers and writers when they remove real friction.

No backend library is part of the durable Scopecat contract. The contract is
the artifact kind, schema record, provenance, diagnostics, and typed reader
behavior.

## Plan Previews

`PlanSnapshot` remains the root record for plan identity, hashes,
diagnostics, acquisition shape, result intents, expected measurement schema,
and preview discovery.

Small plans may keep complete point, parameter-patch, desired-state, and
state-patch previews inline. Large plans should store preview rows as manifest
artifacts and keep summary metadata plus artifact ids in `PlanSnapshot`.

Preview artifacts are planner artifacts, not measurement artifacts. They may
reuse table storage mechanics, but their schemas belong to planning.

Diagnostics that refer to preview rows must use logical sections, row ids,
point ids, and artifact ids. Local file paths are not durable diagnostic
identity.

## Calibration Evidence

Accepted calibration values are accepted `ParameterState` values inside a
configuration snapshot. Do not introduce a second accepted-state root such as
`CalibrationState` for values that can be represented as parameter scalars or
parameter table rows.

Fit outputs, model results, uncertainty, covariance, residuals, classifier
thresholds, quality metrics, figures, and rejected candidates are analysis or
workflow artifacts until review policy chooses parameter patches.

Calibration provenance should be reconstructable from source run manifest,
plan snapshot, measurement artifacts, analysis artifacts, internal parameter
change records, parameter change decisions, candidate config snapshot, registry entry,
activation record, follow-up run, comparisons, and structured run overviews.

Rollback is a config registry operation. Historical evidence, parameter changes,
decisions, and activation records remain immutable.

## Diagnostics

Diagnostics are part of durable boundary behavior. User-facing planning,
storage, analysis, and adapter APIs should report stable diagnostic codes and
logical locations instead of raw exceptions or file paths.

Important diagnostic families include:

- relation lookup and parameter lookup failures;
- schema mismatch and unsupported payload shape;
- unit mismatch and safety-bound violations;
- missing, duplicate, incomplete, or ineligible artifacts;
- chunk gaps and duplicate chunks;
- preview truncation, missing preview artifact, and preview schema mismatch;
- stale candidate expected values and parameter change invalidation;
- activation, rollback, adapter, and backend unsupported-operation failures.

A generated or code-owned diagnostics catalog is preferable to a hand-maintained
docs table. `docs/` should preserve diagnostic policy, not mirror every code.
