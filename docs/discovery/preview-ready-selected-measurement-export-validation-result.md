# Preview-Ready Selected Measurement Export Validation Result

## Status

Implementation-candidate validation result.

This is not an ADR, final schema, package format, GUI design, importer design,
storage architecture, plotting API, or reusable export contract. It records
what the first implementation-shaped candidate proved and where the boundary
should remain narrow.

## Inputs

- [`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md)
- [`preview-ready-selected-measurement-export-plan.md`](preview-ready-selected-measurement-export-plan.md)
- [`preview-ready-selected-measurement-export-implementation-plan.md`](preview-ready-selected-measurement-export-implementation-plan.md)
- `implementation_candidates/selected_measurement_export/`
- `spikes/selected_measurement_export/`
- `tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`

## Validated Boundary

The first implementation candidate validates a narrow structured summary
boundary for preview-ready selected measurement export.

The candidate summary is the product-shaped layer. It is held under
`candidate_summary` in
`tests/fixtures/selected_run_handoff/preview_ready_measurement_export/expected-export-summary.json`.

It can represent:

- explicitly selected measurement IDs;
- per-measurement labels, experiment type, target, source provenance, and
  primary data authority;
- default source and metadata bundle items;
- linked context with user-included, visible-excluded, and missing include
  states;
- source transform policy as normal data handling state;
- declared preview metadata and degraded-preview state;
- warnings for attention-worthy states: local-only source location, missing
  preview metadata, and missing linked context.

The candidate builder remains side-effect free. It does not read source data,
copy files, create archives, render Markdown, infer schemas, open GUIs, or
traverse relation graphs.

## Wrapper And Review Layers

The expected fixture uses a wrapper around `candidate_summary` for fixture and
review context:

- `export_summary_id`;
- expected-output status;
- source fixture name;
- reference semantics for package-relative fixture paths and deferred storage
  identity.

Markdown review output is fixture/reviewer support, not product output. Its
current structure mirrors the same split:

- `Fixture Wrapper`;
- `Candidate Summary Review`;
- `Boundary Notes`.

Candidate-facing Markdown sections are mostly generated from
`candidate_summary`. Fixture semantics and boundary notes remain reviewer
prose around the summary.

## Boundary Changes From Review

The review process removed several category errors:

- fixture/process metadata moved out of the candidate summary and into the
  wrapper;
- `reference_semantics` moved out of candidate output;
- Markdown/report prose such as `claim_guard` moved out of structured summary
  fields;
- warning-code expectation checks stayed in the spike/test wrapper;
- linked context is filtered to selected measurements;
- nested fixture objects are copied or normalized before entering the summary;
- warning output is reserved for degraded, missing, uncertain, or risky states;
- normal source transform policy, visible-excluded include status, and
  non-recursive traversal policy are summary state rather than warnings;
- user/domain conclusion and analysis-lineage disclaimers are reviewer boundary
  notes rather than product summary warnings.

## Still Not Earned

This validation does not earn:

- final measurement, attachment, artifact, relation, or data-shape schema;
- final package/archive format;
- checksum or integrity contract;
- file-copy/package writer behavior;
- import workflow;
- export or import GUI;
- rendered preview or plotting dependency;
- final storage identity or external-reference policy;
- automatic schema inference;
- recursive analysis-DAG traversal;
- support for harder scan shapes such as ragged scans, trace-per-point data,
  array-valued responses, or backend-specific binary containers.

## Remaining Questions

- Is `source_transform_policy` the right field name, or should it become
  `export_data_handling` once file-copy behavior is designed?
- Should future transform cases produce operational warnings only when there is
  an actual declared, unknown, lossy, unavailable, or replacement transform?
- Should the next implementation-shaped candidate be another validation slice,
  either within the measurement-record route or in a different route, before
  promoting any shared model concepts?
- When a package writer is eventually considered, what integrity and
  materialization guarantees are needed beyond this structured summary?

## Current Recommendation

Pause this slice at the structured-summary boundary unless another concrete
task needs it.

The next design move should be either:

- compare another validation slice with a similarly narrow implementation
  candidate, either within the measurement-record route or in a different
  route; or
- use this result as input to a later architecture decision only after another
  slice pressures the same measurement, linked-context, preview, and warning
  concepts.
