# Handoff Engineering Prototype Plan

## Status

Engineering prototype plan, not accepted architecture.

Artifact posture: `internal_validation_summary`. This plan is internal project
memory. It creates no portable package output, public contract, or new
redaction rule. Use
[`discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
when a prototype output is promoted into a portable/export artifact.

## Objective

Validate a production-shaped, route-local module boundary for read-only
Scopecat-authored handoff package use.

The prototype should prove whether the validated handoff slices compose into a
coherent engineering module before accepting final SDK names, package format,
storage import behavior, GUI architecture, plotting stack, or shared
measurement-record domain model.

## Selected Vertical

The first prototype vertical follows the route's accepted-for-now
open-before-import posture:

```text
package directory
  -> manifest preview
  -> read-only package open
  -> package/read view
  -> table, declared plot, linked-context, and finding access
  -> thin CLI or Python entrypoint for local review
```

Writer-to-reader compatibility may be reused as regression evidence when it is
useful, but the first prototype does not need to redesign producer-side
packaging before proving read-only use.

## Discovery Evidence Reused

The prototype starts from the route decisions in
[`decision.md`](../../discovery/routes/measurement-records/handoff/decision.md)
and the consolidation in
[`README.md`](../../discovery/routes/measurement-records/handoff/README.md).
The most relevant slice
evidence is:

- [`contents-preview-validation-result.md`](../../discovery/slices/measurement-records/handoff/contents-preview-validation-result.md)
- [`opener-validation-result.md`](../../discovery/slices/measurement-records/handoff/opener-validation-result.md)
- [`read-view-validation-result.md`](../../discovery/slices/measurement-records/handoff/read-view-validation-result.md)
- [`sdk-view-model-validation-result.md`](../../discovery/slices/measurement-records/handoff/sdk-view-model-validation-result.md)
- [`sdk-ergonomics-spike-validation-result.md`](../../discovery/slices/measurement-records/handoff/sdk-ergonomics-spike-validation-result.md)
- [`preview-shape-view-validation-result.md`](../../discovery/slices/measurement-records/handoff/preview-shape-view-validation-result.md)
- [`visual-review-validation-result.md`](../../discovery/slices/measurement-records/handoff/visual-review-validation-result.md)
- [`gui-view-state-validation-result.md`](../../discovery/slices/measurement-records/handoff/gui-view-state-validation-result.md)
- [`visual-artifact-validation-result.md`](../../discovery/slices/measurement-records/handoff/visual-artifact-validation-result.md)
- [`inspection-workflow-validation-result.md`](../../discovery/slices/measurement-records/handoff/inspection-workflow-validation-result.md)
- [`route-pressure-validation-result.md`](../../discovery/slices/measurement-records/handoff/route-pressure-validation-result.md)
- [`writer-validation-result.md`](../../discovery/slices/measurement-records/handoff/writer-validation-result.md)
- [`round-trip-validation-result.md`](../../discovery/slices/measurement-records/handoff/round-trip-validation-result.md)

The evidence should be preserved as historical validation. Prototype fixtures
may reuse or reshape selected repository-safe cases without rewriting old
validation results solely to match the prototype output shape.

## Prototype Scope

The prototype may introduce route-local models and helpers for:

- package identity and package-directory continuity;
- manifest-only preview;
- package-local primary table reading for preview-ready measurements;
- declared preview metadata and declared plot bindings;
- linked context as reference-only review facts;
- route-local review findings;
- read-only Python-facing access to measurements, tables, plot facts, and
  context references;
- a thin local CLI or Python entrypoint for smoke-testing the route.

These models are handoff projections. They do not need to capture the full
relationship between measurement records, storage, import, running inspection,
parameter state, experiment code, setup binding, or environment operation.

## Non-Scope

The prototype does not accept:

- final package format beyond the tested directory-shaped package subset;
- final public SDK names or stable module layout;
- hard pandas/numpy dependency;
- production plotting library or GUI framework;
- archive extraction, signatures, authenticity, or trust policy;
- linked-context payload packaging, opening, recursive traversal, or import;
- storage import, acceptance, conflict policy, or existing-record update
  behavior;
- numeric dtype inference, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- analysis/fit execution, uncertainty, write-back, or result import;
- shared `core`, `domain`, or measurement-record model.

## Provisional Module Boundary

The prototype should organize code around the handoff route rather than a
global domain layer. A plausible module split is:

```text
scopecat/handoff/
  __main__.py
  _contracts.py
  _manifest_preview.py
  inspect.py
  opener.py
  package.py
  read_only.py
  tables.py
```

The first implementation pass starts in `scopecat/handoff/` because the
repository is currently configured as a non-package project. This tests the
future module boundary without adding packaging metadata or a `src/` install
step during the prototype.

Low-level helpers may be reused from existing implementation candidates only
when their semantics already match the handoff route. New shared helpers should
remain route-local unless at least two concrete implementation consumers need
the same behavior, failure semantics, and tests.

## Initial Implementation Status

The first engineering-prototype pass now exists under `scopecat/handoff/`.
It provides:

- `open_package(package_dir)` as the Python entrypoint;
- `write_package(source, source_root=..., package_root=...)` as the
  source-root package writer entrypoint for declared normalized primary data;
- `run_package_workflow(source, source_root=..., package_root=...)` as the
  local writer -> reader -> optional inspection composition entrypoint;
- route-local `HandoffPackage`, `HandoffMeasurement`, `HandoffTable`, and
  `HandoffFinding`, `HandoffLinkedContext`, and `HandoffPlotSeries`
  projections;
- route-local `HandoffPackageWriteReceipt` projection for local write review;
- route-local `HandoffPackageWorkflowRun` projection for local workflow review;
- a stdlib CLI via `python -m scopecat.handoff <package-dir>` for JSON
  orientation and `--html-dir <dir>` for a local static inspection artifact;
- `build_inspection_html()` and `write_inspection_artifact()` for local
  review output generated from the route-local package projection;
- route-local read-only opener behavior for package manifest loading,
  package-local primary CSV reads, symlink guardrails, declared preview-table
  projection, and declared plot-series construction;
- route-local handoff contract and manifest-preview helpers for package
  identity, package-relative primary-data topology, preview-ready metadata,
  linked-context references, package classification, and review findings;
- typed manifest-preview fragments for identity, primary data, declared
  preview metadata, selected measurements, and linked-context references, so
  raw manifest dictionaries stay at the JSON validation/parsing boundary
  instead of flowing through classification, review-finding construction, or
  opener internals;
- product-shaped package state rather than candidate-shaped summary wrapping:
  manifest-preview findings, linked-context references, declared digest/size
  facts, primary/preview tables, and plot series are exposed as route-local
  objects, with `as_open_summary()` kept only as a copy-safe prototype
  snapshot;
- regression coverage over the basic opener fixture and richer route-pressure
  fixtures, including multi-plot, table-only, shared-context, and degraded
  preview cases;
- a local `scopecat/ruff.toml` that applies stricter lint only to the
  prototype/product-shaped package.

The prototype no longer delegates read-only opening, manifest-preview
classification, package writing, or handoff contract checks to
`implementation_candidates`.
Those discovery candidates remain historical validation evidence. The local
inspection artifact is prototype-local review output; it is not a portable
package member, public report, final GUI component model, dataframe adapter,
package import record, or package-integrity verification.

The writer uses `source_root` terminology at the promoted API boundary. That
keeps the current workflow testable without accepting final Scopecat storage
architecture or archive format.
Writer request dictionaries are boundary input only: the promoted writer
validates and parses them into route-local write-source objects before
preflight, manifest generation, package writes, or receipt serialization.
The workflow composition is deliberately orchestration-only: it proves the
accepted package subset can be written, reopened, and optionally inspected
without promoting archive creation, package import/acceptance, integrity
verification, or final storage layout.

Promotion follow-up decisions resolved by
[`engineering-prototype-promotion-decision.md`](engineering-prototype-promotion-decision.md):

- leading-underscore helper modules stay route-private;
- static HTML remains the first local review surface;
- numeric conversion, dataframe adapters, and plotting-library integration
  remain deferred until a concrete notebook or GUI workflow requires them.

## Fixture Policy

Discovery fixtures and expected outputs remain validation evidence. Prototype
fixtures become engineering regression assets.

The promoted writer fixtures live under
`tests/fixtures/handoff_engineering_prototype_writer/` and use source-root
terminology directly. The older discovery candidate writer fixtures remain
under `tests/fixtures/handoff_package_writer/` as historical evidence for the
candidate shape and are not translated in promoted writer tests.

When existing fixtures do not match the prototype shape:

- keep the original slice fixture if it still represents the historical
  validation result;
- create a prototype fixture when the route needs a cleaner regression case;
- preserve earned behavior such as identity continuity, package-relative
  topology, declared preview authority, reference-only linked context, and
  local finding visibility;
- do not preserve candidate-specific summary nesting or policy prose unless a
  prototype consumer needs it.

Repository-safety review still applies to all fixtures. Runtime redaction is
required only at declared or effective portable/export boundaries.

## Dependencies Under Evaluation

Default to the Python standard library during the first prototype pass.

External dependencies may be introduced only when they answer a concrete
prototype question, such as CLI ergonomics, optional dataframe adaptation, or
rendering behavior. If introduced, record whether the dependency is:

- a prototype-only experiment;
- a route-local implementation decision;
- a candidate for broader product adoption.

Hard dataframe, plotting, GUI, or packaging dependencies remain deferred until
a narrower workflow earns them.

## Validation Plan

The prototype should add or reuse tests that cover:

- happy-path read-only package open and read access;
- manifest preview before package-local file reads;
- package identity and selected-measurement continuity;
- canonical primary-data package topology;
- declared preview metadata and plot binding behavior;
- table-only and degraded-preview cases;
- reference-only linked context visibility;
- one negative test per new managed field category or boundary narrowing;
- CLI or Python entrypoint smoke behavior if exposed.

Repository verification remains:

```text
uv run python -m unittest discover -s tests
uv run prek run --all-files
```

## Stop Conditions

Stop the prototype when the selected vertical has:

- one usable local Python or CLI entrypoint;
- regression coverage from representative handoff fixtures;
- documented prototype contracts and non-claims;
- green repository tests and hooks;
- a written promotion decision that chooses one of: promote, revise, split,
  discard, or return to targeted discovery.

The prototype is not done merely because code exists. It is done when it has
answered the module-boundary and workflow-composition question.

## Promotion Criteria

Promote the prototype toward accepted implementation only if:

- the read-only workflow is coherent for package orientation and local review;
- route-local models improve implementation clarity without becoming a
  premature global domain model;
- fixture-derived regression tests protect the earned handoff behavior;
- candidate-specific output shapes have been intentionally kept or left behind;
- remaining deferred decisions are named and do not block the accepted
  vertical.

If multiple routes later need the same lifecycle, validation behavior, and
failure semantics, reconsider shared model extraction with a narrower accepted
decision or ADR.

Current stop-criteria assessment is recorded in
[`engineering-prototype-readiness.md`](engineering-prototype-readiness.md);
the promotion decision is recorded in
[`engineering-prototype-promotion-decision.md`](engineering-prototype-promotion-decision.md).

## Remaining Follow-Up Questions

- Which old implementation candidates can be archived, left untouched as
  evidence, or ignored by future maintenance after branch merge?
- Which separately scoped route extension should resume next: notebook
  adapters, GUI review, storage acceptance, archive/trust, linked-context
  payloads, or analysis/fit results?
