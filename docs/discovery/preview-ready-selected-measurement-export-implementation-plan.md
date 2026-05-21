# Preview-Ready Selected Measurement Export Implementation Plan

## Status

Concrete implementation-planning draft.

This is not an ADR, final schema, package format, GUI design, importer design,
storage architecture, plotting API, or reusable export contract. It translates
the validated preview-ready selected measurement export slice into the smallest
code-facing plan that can be implemented and tested without reopening the full
product model.

Owning discovery boundary:
[`preview-ready-selected-measurement-export-plan.md`](preview-ready-selected-measurement-export-plan.md).

First executable pressure fixture:
`tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`.

Clean candidate summary fixture field:
`tests/fixtures/selected_run_handoff/preview_ready_measurement_export/expected-export-summary.json`
under `candidate_summary`.

Current bounded spike:
`spikes/selected_measurement_export/`.

First implementation candidate:
`implementation_candidates/selected_measurement_export/`.

## Implementation Goal

Add a thin export-planning layer that can produce a reviewer-facing selected
measurement export summary from explicit measurement, bundle, linked-file, and
preview metadata records.

The first implementation should prove that Scopecat can:

- treat selected measurements as the explicit export set;
- include default primary data and copied metadata for selected measurements;
- distinguish user-included, visible-excluded, missing, and local-only linked
  context;
- carry source provenance separately from package-relative materialized files;
- carry source transform policy as normal data handling state;
- expose declared preview metadata when available;
- degrade preview explicitly when preview metadata is missing;
- avoid automatic schema inference and recursive relation traversal.

Normal export policies and boundary disclaimers should not be emitted as
candidate warnings. The structured summary may carry source transform policy,
include status, and traversal policy as ordinary state. Warnings should be
reserved for degraded, missing, uncertain, or risky states such as local-only
references, missing linked context, or missing preview metadata.

The first implementation should not create a real package archive, GUI preview,
import flow, storage backend, or plotting surface.

## First Code Boundary

The first product-shaped code should be a pure builder with deterministic input
and output:

```text
SelectedMeasurementExportInput
  -> build_selected_measurement_export_summary(...)
  -> SelectedMeasurementExportSummary
```

The builder should be side-effect free. It should not copy files, read source
CSV contents, inspect notebooks, infer columns, create archives, open GUIs, or
write output paths. File existence/openability checks may stay in fixture tests
until a storage or package writer decision is earned.

The structured summary is the first implementation boundary. Markdown review
rendering is fixture and reviewer support only: it helps humans inspect whether
the structured summary explains the fixture clearly, but it is not a product
report surface or durable output requirement. Future export-side and import-side
preview surfaces should consume structured data, not depend on Markdown.

This boundary keeps implementation pressure on the data model and warnings
without committing to the final IO layer, GUI, or report format.

## Summary Field Discipline

The structured summary should not become a catch-all container for possible
future UI, importer, plotting, or storage needs.

Include a field only when it supports a current acceptance question:

- what was intentionally selected;
- what is included by default;
- what optional context was included, excluded, or missing;
- where selected data came from;
- which source data should not be silently transformed;
- whether preview metadata is declared or missing;
- which warning affects export trust or orientation.

Do not add fields only because a later GUI, import workflow, relation model, or
plotting surface might want them. Add those fields when that later slice is
validated and has its own acceptance question.

If a field is included, the fixture, expected output, or documentation should
make clear what user question, warning, or boundary decision it supports.

## Candidate Fixture-Aligned Inputs

Use explicit inputs close to the fixture vocabulary. These are test-facing
implementation shapes for the first slice, not persistent model names or final
schema concepts. Names may change during implementation, but the first code
should represent these concepts directly:

- `SelectedExportSet`: selection mode, selected measurement IDs, traversal
  policy, and traversal note.
- `MeasurementRecord`: stable identifier, label, experiment type, target,
  source provenance, primary data reference, source-transform expectation, and
  optional preview metadata.
- `BundleItem`: kind, label, package/materialized reference, include status,
  relation, and authority.
- `LinkedContextItem`: kind, label, reference, include status, relation,
  authority, linked measurement IDs, and optional note.
- `PreviewMetadata`: status, authority, declared shape, declared roles, labels,
  units, plot candidates, and degraded-preview warning when missing.
- `ExportWarning`: code, subject, and message for operational export
  orientation.

Do not introduce a general relation graph, artifact ownership model, storage
object model, checksum contract, or package manifest schema in this step. The
records above are implementation scaffolding for one validated slice.

## Fixture Mapping

Map the existing integrated fixture directly:

- `selected_export_set` maps to `SelectedExportSet`;
- `measurements[*]` maps to `MeasurementRecord`;
- `measurements[*].default_bundle[*]` maps to `BundleItem`;
- `linked_context[*]` maps to `LinkedContextItem`;
- `preview_metadata` maps to `PreviewMetadata`;
- `warnings_expected` remains an acceptance check for emitted warning order and
  coverage;
- `source_file`, `path`, and plot candidate `source` remain package-relative
  fixture references;
- `export_source` remains recoverable source provenance, not a read path;
- `local_path` remains external, redaction-sensitive, and non-portable.

Required input fields should continue to appear in fixtures and tests. Builders
and test helpers should not silently supply required values.

## Implementation Phases

### Phase 1: Promote The Spike Shape Into A Structured Summary Boundary

Create a production-shaped experimental module for the pure structured-summary
builder only if that helps test the next code boundary. The current candidate
location is `implementation_candidates/selected_measurement_export/`; it is a
narrow temporary area, not an accepted package layout. Avoid shared names like
`core`, `domain`, or `models` until multiple slices earn those concepts.

Move only the behavior that is already fixture-backed:

- selected-ID filtering;
- primary data reference consistency;
- plot candidate source consistency;
- default/user-included/visible-excluded/missing grouping;
- preview-ready versus degraded-preview output;
- structured warning output.

Expected warning-code order and coverage should stay in tests or fixture
helpers. The builder emits warnings; fixture acceptance checks that they match
the declared expectation.

Reference semantics remain fixture/reviewer documentation around the candidate
summary. They should not be emitted by the candidate builder as selected-export
data.

Markdown review rendering may remain a fixture/test helper that reads the
structured summary. It should not define the production boundary.

Keep the old spike as historical validation or remove it only if the new module
fully replaces the tested behavior and docs are updated together.

### Phase 2: Make Acceptance Tests Target The New Boundary

Add or move tests so the integrated fixture proves the production-shaped module
can produce:

- the expected summary JSON;
- enough structured data for the expected Markdown review helper to explain the
  fixture;
- degraded preview without header inference;
- source provenance preservation;
- selected-only export membership;
- primary data and plot candidate reference consistency failures;
- exact warning-code coverage.

Tests should still use the public-safe fixture. They should not require real
LabRAD, Labber, notebook, HDF5, NPZ, GUI, plotting, or dataframe dependencies.

### Phase 3: Decide Whether A Package Writer Is Actually Needed

Only after the pure summary builder passes should the project decide whether the
next step is a materialized package writer.

If added, the first package writer should be separate from the builder and
should accept the already-built summary plus explicit source file references.
It should still avoid final archive format, checksum, importer, GUI, and
storage identity decisions unless those become blockers.

The current slice does not require this phase.

## Acceptance Criteria

This implementation-planning slice is ready to turn into work when it can be
expressed as one or two small engineering tasks:

- implement the pure selected measurement export summary builder;
- keep Markdown review rendering as fixture/reviewer support if it remains
  useful;
- keep all behavior covered by
  `tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`;
- update docs, fixtures, tests, and expected outputs together for any public
  output or boundary change.

The first implementation is done when:

- fixture-level tests pass against the production-shaped boundary;
- warning codes remain explicit and ordered;
- missing preview metadata degrades preview without blocking export;
- selected source data is not silently replaced by derived artifacts;
- visible-excluded context is not treated as selected or included;
- the implementation still does not infer schema, traverse relation graphs, or
  claim user/domain conclusions.

## Stop Conditions

Stop and return to product/design review if implementation requires any of
these before the pure builder can pass:

- final measurement, artifact, attachment, or many-to-many relation schema;
- final managed storage identity model;
- external-reference-only workflow guarantees;
- package/archive format;
- checksum or integrity contract;
- export or import GUI decisions;
- rendered plot preview or interactive slicing;
- automatic scan-shape inference;
- recursive analysis-DAG traversal;
- support for ragged scans, trace-per-point data, array-valued measurements, or
  backend-specific binary containers.

Those may become future slices, but they should not be smuggled into this one.

## Open Implementation Questions

These are useful to answer before writing production code, but they should be
kept narrow:

- Where should the first production-shaped pure builder live before the broader
  package layout exists?
- Should the spike remain as a validation artifact after the builder is
  promoted, or should tests move entirely to the new module?
- Should the first summary type be plain dictionaries, dataclasses, typed
  dictionaries, or pydantic-style models if a dependency is later accepted?
- Should warning-code ordering be treated as a stable review-output behavior or
  only as fixture-level acceptance detail?
- How much of the current Markdown review helper should remain once structured
  summary tests are owned by production-shaped code?

## Not Yet Earned

This implementation plan does not earn:

- a reusable Scopecat export contract;
- a final manifest schema;
- a final data-shape model;
- a storage or package identity model;
- a GUI workflow;
- a data preview implementation;
- an importer;
- an artifact inclusion UX;
- an analysis-lineage DAG;
- a guarantee that this slice covers all adoption hypotheses.
