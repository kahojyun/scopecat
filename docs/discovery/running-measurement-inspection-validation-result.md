# Running Measurement Inspection Validation Result

## Status

Fixture validation result.

This is not an ADR, final lifecycle schema, live service contract, reader API,
plotting API, GUI design, storage schema, ndarray indexing API, callback
contract, execution framework, package/export behavior, or hardware-control
decision. It records what the current running-inspection fixtures proved and
where the boundary should remain narrow.

## Inputs

- [`problem-briefs/running-measurement-inspection.md`](problem-briefs/running-measurement-inspection.md)
- [`running-measurement-inspection-validation-plan.md`](running-measurement-inspection-validation-plan.md)
- `tests/fixtures/running_measurement_inspection/partial_sweep/`
- `tests/fixtures/running_measurement_inspection/partial_heatmap/`
- private source-code review notes for running-inspection plotting and analysis
  pressure.

## Validated Boundary

The fixtures validate a narrow state-summary boundary for inspecting
already-recorded data from a still-running measurement.

The same summary categories work for both current fixture shapes:

- a repeated 1D sweep with a complete previous sweep and incomplete current
  sweep;
- a 2D heatmap-shaped table with a complete rectangular prefix and incomplete
  current grid row.

The summary can represent:

- measurement identity, label, target, experiment type, and source identity;
- lifecycle state, start time, last update time, and recording-enabled state;
- expected and recorded progress counts;
- latest complete unit and current partial unit;
- objective completeness, completeness basis, and default-preview candidate
  hints;
- preview metadata: shape kind, axis order, row order, declared roles, units,
  and plot candidates;
- latest data reference for the already-recorded fixture data;
- explicit freshness basis for attention warnings;
- non-durable monitor ergonomics such as selected range, selected region, fit
  preview, or feature marker;
- saved decisions only when explicitly present.

## Important Separations

The fixtures clarified several boundaries that should be preserved:

- `complete` is an objective structural property of a declared fixture slice.
- `completeness_basis` explains why a slice is complete or incomplete.
- `default_preview_candidate` is a hint for the stable slice a simple monitor
  may choose first; it is not a GUI visibility rule.
- Incomplete running data can still be visible as normal state.
- Partial progress is not a warning by itself.
- Warnings are reserved for attention-worthy conditions with explicit basis,
  such as stale data, missing preview metadata, unavailable storage, disabled
  recording, or ambiguous completeness when completeness is required.
- Temporary fit previews, selected ranges, selected regions, and feature
  markers are monitor ergonomics, not durable analysis records.

## Sample-Code Pressure

The sample-code review suggests live preview and simple analysis often depend
on information beyond raw data rows:

- axis order and row ordering;
- independent/dependent labels and units;
- static conditions and selected measured targets;
- selected run IDs;
- expected totals versus observed counts;
- whether completed artifacts, live files, or sidecar metadata are being read;
- whether incomplete tails are explicit instead of silently dropped for
  reshaping.

The current public fixtures incorporate only the pressure needed for the first
running-inspection slice: explicit progress, row order, roles, units,
freshness basis, complete slices, and partial tails. Paired selected IDs,
sidecar metadata files, completed-artifact preference, sparse grids, ragged
grids, and array-valued measurements remain future pressure cases.

## Still Not Earned

This validation does not earn:

- final lifecycle or progress schema;
- final measurement/data-shape schema;
- live service, websocket, callback, or event-stream API;
- GUI implementation or GUI visibility rules;
- plotting dependency or plotting API;
- ndarray-style indexing or slice-selection API;
- analysis-readiness taxonomy;
- fit quality validation or user/domain scientific conclusions;
- storage authority, reader authority, or source-of-truth decision;
- package/export/import behavior;
- hardware control, scan-plan mutation, automatic retune, or parameter
  write-back.

## Remaining Risks

- Rectangular-prefix heatmap coverage does not prove support for sparse grids,
  ragged scans, trace-per-point data, or array-valued responses.
- The fixtures use declared metadata. They do not validate discovery or
  inference from legacy sidecars, file names, or framework-specific readers.
- The fixtures show non-durable monitor ergonomics, but do not validate a real
  monitor interaction model.
- Freshness thresholds are fixture-declared. A real system still needs a
  product decision about who sets those thresholds and how noisy they should be.
- Paired selected-ID analysis, such as signal/background comparison, is not
  covered by this slice.

## Current Recommendation

Pause running-inspection at the fixture-validation boundary unless a concrete
task needs a generator.

A tiny generator could be useful to keep expected JSON honest, but it is not
required to answer the current product-boundary question. The better next
design move is probably to compare another validation slice before promoting
any shared lifecycle, preview, completeness, warning, or data-shape concepts
into a broader implementation contract.
