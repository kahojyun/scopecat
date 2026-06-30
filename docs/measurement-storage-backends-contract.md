# Measurement Storage Backends Contract

Status: accepted design baseline
Date: 2026-06-27

This note records the measurement storage decisions that build on
[Storage Workspace And Manifest Contract](storage-workspace-manifest-contract.md).
It is the implementation baseline for scalar rows, typed tables, typed arrays,
chunked data, and future larger backends.

The purpose is to keep measurement semantics stable while allowing storage
formats to change. A backend may use JSONL, JSON, Parquet, Arrow, Zarr, HDF5,
or another file/object format, but consumers should discover and validate data
through typed Scopecat records and artifact metadata.

## Current Baseline

Scopecat currently has these measurement storage records:

- `MeasurementRecord`: one scalar row for a logical point or point/shot record.
- `MeasurementDatasetSchema`: dataset id, role, dimensions, variables,
  primary coordinates, primary observables, and variable links.
- `MeasurementDataset`: row-facing wrapper around `MeasurementRecord` values
  and a dataset schema.
- `DataTableArtifact`: typed table payload with `DataTableSchema`.
- `DataArrayArtifact`: typed labeled-array payload with `DataArraySchema`.
- `ChunkedArtifactManifest`: completion record for chunked artifact assembly.
- `ArtifactAvailabilityReport`: point eligibility report for required and
  optional artifact refs.

The current implementation serializes scalar measurements as JSONL and small
tables/arrays as JSON. That is an implementation baseline, not a durable limit.

## Durable Measurement Contract

The durable measurement contract is:

- Measurement semantics live in schemas and typed payload records, not in file
  extensions.
- `MeasurementDataset` remains the row-facing contract for scalar point data.
- `MeasurementDatasetSchema` remains the shared semantic schema for point-row
  datasets and for describing related variables across richer artifacts.
- `DataTableArtifact` and `DataArrayArtifact` are not replacements for
  `MeasurementDataset`; they are artifact-backed shapes for tabular and
  labeled-array data that do not fit the scalar row stream.
- Chunk manifests are artifacts with typed payloads. They are not manifest
  indexes and should not introduce a new top-level `RunManifest` list.
- Every persisted measurement shape is discovered through
  `RunManifest.artifact_refs` and selected by artifact id, kind, media type,
  and metadata.
- Every measurement artifact must carry enough provenance to prove source run,
  source point scope, source step or adapter, schema version, and upstream
  artifact dependencies.

## Shape Ownership

Use scalar row datasets when:

- the data is one record per logical point, shot, repeat, or decoded summary;
- coordinates and observables are scalar `Quantity` values;
- run comparison, best-point selection, or analysis can consume rows without
  opening a richer payload.

Use typed table artifacts when:

- the data is sparse or non-orthogonal;
- columns have roles such as identifier, coordinate, observable, uncertainty,
  status, mask, or metadata;
- the data is a fit summary, probability table, report-ready table, imported
  table, or derived analysis output.

Use typed array artifacts when:

- variables have named dimensions and regular shapes;
- the data is an IQ cloud, spectrum, waveform, image, matrix, dense model
  output, or other labeled N-dimensional payload;
- uncertainty, status, or mask variables must align with the same dimensions.

Use chunk manifests when:

- a table or array is written incrementally;
- a backend returns ordered fragments before the final artifact is complete;
- duplicate, missing, or final-chunk diagnostics must be auditable.

Use events or workflow records when:

- the information is an online decision, adapter progress event, retry summary,
  early-stop decision, resume decision, or operator annotation;
- the information describes execution policy rather than measured values.

Keep richer future shapes behind the same ownership rules. Repeated shots,
IQ clouds, spectra, waveforms, images, probability tables, fit summaries,
classifier outputs, retry summaries, early-stop decisions, and resume decisions
should be represented as row datasets, typed table artifacts, typed array
artifacts, events, or workflow records according to their shape. Do not turn
`MeasurementRecord.metadata` into an untyped catch-all model.

## Provenance Requirements

Every persisted measurement artifact should carry these fields either directly
in the payload or in artifact metadata:

- schema version of the payload;
- dataset id or artifact id;
- dataset role such as raw or derived;
- source `run_id`;
- `plan_content_hash` when the data is point-scoped;
- point identity field when records are scoped below a whole run;
- source adapter, processing step, or evaluation step id;
- source artifact ids for derived data;
- config/profile or parameter-build identity when needed for replay;
- units and variable roles through the schema;
- diagnostics for incomplete, rejected, masked, or invalid data.

The minimum currently accepted metadata keys are:

- `dataset_role`
- `record_schema` for scalar row datasets
- `dataset_schema` for scalar row datasets
- `data_shape` for table or array artifacts
- `data_schema` for table or array artifacts
- `source_step` when created by a reusable `AnalysisStep`
- `source_artifact_ids` for upstream artifacts

Path-style upstream refs are local compatibility debt and should stay at
storage boundaries instead of durable artifact metadata.

## Backend Direction

The storage backend is an implementation choice behind typed readers and
writers:

- JSONL remains the small scalar-row baseline and adapter-friendly interchange
  format.
- JSON remains acceptable for small table, array, chunk manifest, availability,
  and report-adjacent records.
- Parquet or Arrow are the likely first large scalar/table backend.
- Zarr or NetCDF are the likely first large labeled-array backend.
- HDF5 or NeXus may be useful for instrument-native raw arrays, but should
  enter as artifact-backed payloads rather than as workspace layout.

Do not make a backend library part of the durable Scopecat contract. The
contract is the artifact kind, schema record, provenance, and typed reader
behavior.

## Dataset Indexing

Measurement storage should use the manifest artifact index defined by the
storage contract:

- Store each dataset, table, array, chunk manifest, or availability report as
  an `Artifact`.
- Use artifact `kind` values to identify shape families, for example
  `measurement_dataset`, `data_table`, `data_array`,
  `chunked_artifact_manifest`, and `artifact_availability_report`.
- Keep the detailed variable schema inside artifact metadata or payload.
- Do not add new top-level `RunManifest` lists for table datasets, array
  datasets, chunk manifests, backend partitions, or preview outputs.
- Do not reintroduce the former `measurement_dataset_refs` field; measurement
  datasets are discovered through `artifact_refs` with kind
  `measurement_dataset`.

This keeps plan preview artifacts, analysis outputs, reports, run comparisons,
and measurement backends discoverable through the same manifest graph.

## Relationship To Future Design Notes

`PlanSnapshot` preview storage:

- Preview point rows, patch rows, and state rows should use table-like artifact
  schemas when they become too large to keep inline.
- Preview artifacts may reuse table/array storage mechanics, but their schemas
  are planner contracts rather than measurement contracts.

Relation execution scale:

- Relation engines may produce large point or parameter tables, but those are
  preview/planner artifacts until acquisition creates measurement outputs.
- Measurement backends should not expose a relation engine as their durable
  file format.

Calibration state:

- Fit outputs, uncertainty, covariance, and quality metrics are analysis
  artifacts until a calibration-state design promotes some fields into accepted
  state.
- Candidate review should reference the measurement and fit artifact ids that
  justify a state update.

Diagnostics catalog:

- Measurement storage diagnostics should stabilize around schema mismatch,
  missing variable, unit mismatch, chunk gap/duplicate, incomplete artifact,
  and artifact eligibility families.

## Accepted Decisions

- `MeasurementDataset` remains the scalar row-facing contract.
- `MeasurementDatasetSchema` remains the shared semantic schema for measurement
  variable roles, dimensions, units, and links.
- Typed table and array artifacts are first-class measurement-adjacent storage
  shapes, not metadata blobs.
- Chunk manifests are typed artifacts and not dataset indexes.
- All measurement shapes are discovered through `RunManifest.artifact_refs`.
- New measurement records should prefer artifact ids for source refs.
- Backend libraries are implementation details behind typed artifact readers.

## Deferred Questions

- Exact artifact kind names for future Parquet, Arrow, Zarr, NetCDF, HDF5, or
  NeXus payloads.
- Whether scalar row datasets should gain a dedicated point id in addition to
  `point_index`.
- Whether `MeasurementDatasetSchema` and `DataTableSchema` should converge on
  a shared variable/column base model.
- Whether value-level uncertainty and status should extend `Quantity` or remain
  variable-level schema links.
- Whether chunk manifests should reference chunk artifact ids instead of chunk
  paths once id-based source refs are fully migrated.
- Which storage backends, if any, should become optional extras in package
  metadata.
