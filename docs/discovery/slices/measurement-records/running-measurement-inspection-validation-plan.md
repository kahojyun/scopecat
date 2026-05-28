# Running Measurement Inspection Validation Plan

## Status

Validation-planning draft.

This is not an ADR, product contract, storage schema, GUI design, live monitor
implementation, reader API, plotting API, execution framework, callback
contract, or hardware-control decision. It defines the first narrow validation
question for the running measurement inspection slice.

Owning problem brief:
[`problem-briefs/running-measurement-inspection.md`](../../problem-briefs/running-measurement-inspection.md).

Related evidence:
`EV-046` and `EV-047` in [`../evidence/evidence-register.md`](../../../evidence/evidence-register.md).

## Validation Question

Can Scopecat represent enough explicit running-measurement state for a user or
simple monitor to inspect already-recorded data and decide whether to keep
watching, intervene outside Scopecat, or stop, without Scopecat owning
instrument control or scan-plan mutation?

The slice should pressure a live/in-progress workflow rather than export or
handoff. It should test whether the measurement-record concepts from selected
measurement export are too static.

## User Job

During a long-running measurement, a user wants to inspect the latest usable
recorded data before the full run finishes.

The user needs to know:

- which measurement is currently running;
- what portion of data has already been recorded;
- whether a structurally complete default preview candidate exists;
- whether preview metadata is enough to orient a monitor;
- whether the latest data is stale, partial, unavailable, or incomplete;
- whether the run is still recording, paused, interrupted, stopped, or done;
- whether any manual decision or fit result has been saved.

## First Fixture Concept

Start with a synthetic public-safe fixture, not product code:

- one running measurement with an explicit measurement ID and label;
- declared sweep or scan shape for preview orientation;
- recorded rows or chunks that are intentionally partial;
- progress state such as points recorded, expected points, current sweep index,
  or latest completed slice;
- lifecycle state such as `recording`, `paused`, `interrupted`, `stopped`, or
  `complete`;
- latest complete unit, such as latest completed sweep, latest complete row, or
  latest complete chunk, plus whether it is a default preview candidate;
- preview status, degraded-preview state, preview-unavailable state, and row
  ordering when it matters for plotting or reshape assumptions;
- attention-worthy warnings such as stale data, missing preview metadata,
  ambiguous required completeness, recording disabled, or storage unavailable, with the
  fixture-declared warning basis made explicit;
- optional ephemeral monitor actions such as selected range or temporary fit,
  only when they are explicitly not durable records;
- saved operator decisions or fit results only if the user explicitly saves
  them.

The fixture should avoid export/package fields unless needed for comparison.

First fixture:
`tests/fixtures/running_measurement_inspection/partial_sweep/`.

Second fixture:
`tests/fixtures/running_measurement_inspection/partial_heatmap/`.

The second fixture exists only to check that the same state categories can
describe a simple 2D heatmap inspection case. It should not pull ragged scans,
array-valued measurements, final plotting contracts, or storage schema design
into the current slice.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate summary
should be a pure structured output, not a GUI or live service:

```text
RunningMeasurementInspectionInput
  -> build_running_measurement_inspection_summary(...)
  -> RunningMeasurementInspectionSummary
```

The candidate summary may include:

- `measurement`: identifier, label, target, experiment type, and source
  identity;
- `lifecycle`: current state, started time if known, stop/interruption state if
  known;
- `progress`: recorded count, expected count if known, latest completed unit,
  objective completeness markers, completeness basis, default-preview hints,
  and partial/incomplete markers;
- `preview`: declared shape, roles, candidate axes/responses, and degraded
  preview state;
- `latest_data_reference`: package-relative fixture reference or candidate
  read reference for already-recorded data;
- `attention`: warnings for stale, missing, unavailable, or completeness-ambiguous
  state;
- `ephemeral_monitor_state`: optional non-durable range selection or fit preview
  only when needed to explain monitor usefulness;
- `saved_decisions`: durable operator decisions or saved fit results only when
  explicitly present.

Completeness should be treated as a structural fact about a declared fixture
slice, not as a GUI visibility rule. Incomplete running data can still be shown;
`default_preview_candidate` only marks the fixture's stable slice as a candidate
a simple monitor may choose first. This does not define final ndarray-style
indexing, slice-selection APIs, analysis readiness, or GUI behavior.

Normal state should not be emitted as a warning. For example, `recording`,
`partial`, or `non_final` can be ordinary lifecycle/progress state. Warnings
should be reserved for attention-worthy conditions: stale data, missing preview
metadata, storage unavailable, recording disabled, or a latest slice whose
completeness is ambiguous when completeness is required.

Sample-code pressure suggests that plotting and simple analysis often depend on
axis order, dependent names and units, static conditions, selected run IDs, and
whether incomplete tails are explicitly surfaced rather than silently reshaped
away. This plan records those as fixture pressure, not as final storage,
indexing, or plotting contracts.

## Boundary

Do not include these in the first slice:

- hardware control;
- scan-plan mutation;
- automatic retune;
- automatic parameter write-back;
- framework scraping;
- passive discovery of arbitrary files;
- GUI implementation;
- live websocket/service design;
- plotting dependency;
- fit quality validation;
- durable cursor or range-selection records by default;
- package/export/import behavior;
- final lifecycle or progress schema.

Range selection and preview fits may appear in the fixture only as monitor
ergonomics. They should not become durable records unless the user saves a fit
result or operator decision.

## Comparison Pressure Against Export Slice

This slice should test whether the export candidate's concepts generalize:

- `measurement` remains useful before completion;
- preview readiness can be partial or degraded without blocking inspection;
- warnings mean attention-worthy state, not normal policies or boundary
  disclaimers;
- linked context is less central than lifecycle/progress for live inspection;
- source identity matters, but live source/read references may be unstable or
  not yet portable;
- package-relative paths should not leak into the core running-inspection
  concept.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small running-inspection fixture;
- define expected summary output with wrapper and candidate-summary separation;
- optionally add a tiny generator only if it helps keep expected output honest;
- compare the resulting candidate summary against the selected measurement
  export boundary.

Do not promote an architecture decision from this slice alone.
