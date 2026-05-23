# Running Measurement Inspection Validation Result

## Status

Implementation candidate validated.

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
- [`../../implementation_candidates/running_measurement_inspection/`](../../implementation_candidates/running_measurement_inspection/)
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
- absence of saved decisions for the current fixtures, while durable
  saved-decision records remain deferred.

The implementation candidate builds this summary from explicit fixture input
only. It validates the declared source identity, relative latest-data reference,
progress completeness/default-preview separation, count consistency for the
two earned fixture shapes, latest-completed filters, preview status/source,
preview axis and plot-candidate column references, monitor axis references,
freshness basis, and non-durable monitor state without opening source data or
polling a live process. It does not validate free labels, units, row-order
semantics, plot renderability, or scientific meaning.

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

## Implementation Boundary

The candidate intentionally returns only `candidate_summary` content. It does
not include validation wrapper fields such as `reference_semantics`,
`source_fixture`, or `status`.

The candidate rejects fixture claims that would blur the boundary:

- private or unredacted source identity;
- absolute or parent-traversing latest-data paths;
- plot candidates that do not reference the latest data file or declared
  columns;
- silently promoting the current partial unit to the default preview
  candidate;
- internally inconsistent progress counts for the two earned fixture shapes;
- latest-completed filters that do not match declared columns or the latest
  completed unit;
- durable monitor state;
- unknown monitor-state fields that would pass through unreviewed payloads;
- non-empty saved decisions before a durable saved-decision fixture exists;
- observation timestamps that predate the latest recorded update.

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
  monitor interaction model or durable saved-decision records.
- Freshness thresholds are fixture-declared. A real system still needs a
  product decision about who sets those thresholds and how noisy they should be.
- Paired selected-ID analysis, such as signal/background comparison, is not
  covered by this slice.

## Slice Recommendation

Pause running-inspection at this implementation-candidate boundary unless a
concrete workflow needs a live adapter, a monitor interaction model, or harder
data-shape pressure.

The implementation candidate is enough to generate the `candidate_summary`
portion of the two current preview-ready public-safe fixtures. The wrapper
fields, boundary notes, and decisions-not-earned remain validation
documentation. The better next design move is still to compare another
validation slice before promoting any shared lifecycle, preview, completeness,
warning, or data-shape concepts into a broader implementation contract.
