# Handoff Engineering Prototype Readiness

## Status

Frozen engineering prototype readiness checkpoint, not an ADR.

This document records the stop/readiness assessment that justified ending the
prototype line. Do not update it to mirror later API additions or mutation-slice
decisions. Current accepted implementation boundaries live in
[`engineering-prototype-promotion-decision.md`](engineering-prototype-promotion-decision.md).

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
if any prototype output is promoted into a portable/export artifact.

## Readiness Judgment

The handoff package engineering prototype is ready to stop broad prototype
expansion and move into a decision-gated implementation phase.

At this checkpoint, the accepted route-local boundary covered the first
directory-package workflow:

```text
caller-provided source root
  -> source-root package writer
  -> directory-shaped package subset
  -> manifest validation and preview classification
  -> read-only integrity observation
  -> approved read-only receiving gate
  -> read-only package open
  -> package, measurement, table, declared plot, linked-context, and finding access
  -> optional local static HTML inspection
  -> local workflow receipt
```

This does not promote final SDK names, package archive format, storage import,
package acceptance, GUI architecture, dataframe dependency, plotting
dependency, signature/authenticity verification, linked-context payload
traversal, or a shared measurement-record domain model.

## Stop Criteria Check

| Criterion | Status | Assessment |
| --- | --- | --- |
| Usable local Python or CLI entrypoint | Met | `open_package(package_dir)`, `observe_package_integrity(package_dir)`, `run_receiving_gate(...)`, `write_package(...)`, `run_package_workflow(...)`, and `python -m scopecat.handoff <package-dir>` exist. |
| Representative regression coverage | Met | Tests cover source-root writing, writer-to-reader round trip, local workflow composition, read-only integrity observation, read-only receiving gate, basic opener, richer route-pressure package, multi-plot, table-only, shared context, degraded preview, CLI, HTML artifact, symlink guardrails, and typed manifest/write boundaries. |
| Documented contracts and non-claims | Met | The route plan, consolidation, decision note, and prototype README define directory-package subset scope, source-root writer scope, local workflow posture, artifact posture, dependency deferrals, and non-claims. |
| Green repository verification | Met | Current milestone verification uses `uv run python -m unittest discover -s tests`, `uv run ruff check .`, and `uv run ruff format --check .`. |
| Written promotion decision path | Met by this note | The next step is a separate acceptance/import or storage-requirements decision, not additional broad handoff expansion. |

## Keep As Implementation Shape

These choices are strong enough to carry into the promotion pass:

- route-local `src/scopecat/handoff/` module boundary;
- source-root package writer API that does not imply final Scopecat storage
  architecture;
- local writer -> reader -> optional inspection workflow composition;
- read-only package integrity observation over manifest-declared package
  members;
- read-only receiving gate over explicit approval and reviewed package,
  preview, and integrity facts;
- raw JSON/dict validation at the package manifest boundary;
- raw write-request validation and parsing at the writer boundary;
- typed route-local manifest fragments after validation;
- product-shaped `HandoffPackage`, `HandoffMeasurement`, `HandoffTable`,
  `HandoffPlotSeries`, `HandoffFinding`, and `HandoffLinkedContext`
  projections;
- local `HandoffPackageWriteReceipt` and `HandoffPackageWorkflowRun`
  projections;
- manifest-only preview classification before package-local file reads;
- package-directory and package-id continuity;
- canonical primary data topology,
  `measurements/{measurement_record_id}/primary.csv`;
- declared preview metadata as the preview authority;
- string-valued table and declared plot projections without dataframe or
  numeric inference semantics;
- linked context as visible reference-only review state;
- static local HTML as the current review artifact.

## Keep Deferred

These are not blockers for the accepted local handoff vertical:

- final public SDK naming and packaging metadata;
- hard pandas/numpy dependency;
- matplotlib or production plotting integration;
- live GUI components or routing;
- numeric dtype conversion, schema inference, unit conversion, scan-shape
  inference, trace opening, or array APIs;
- archive extraction, compressed package format, signatures, authenticity, or
  trust policy;
- package receiving, import, acceptance, conflict handling, storage writes, or
  existing-record update;
- linked-context payload packaging, opening, recursive traversal, or import;
- analysis/fit result model, execution, uncertainty, write-back, or import;
- shared measurement-record domain model or cross-route lifecycle model.

## Current Phase Boundary

At this checkpoint, the route boundary was strong enough for local package
writing, opening, inspection, and workflow review. The next phase was expected
to choose one of these paths:

- receiving/import acceptance: define the first storage mutation after the
  read-only receiving gate without yet committing to final storage layout;
- storage requirements synthesis: compare source-root writer, legacy import,
  existing-record update, handoff receiving, and source-observation needs
  before accepting a storage/archive format.

Do not start final archive, storage schema, or package-import implementation
until one of those decision paths is explicit.

## Remaining Risks

- The static HTML renderer is acceptable for the first local review surface,
  but should not become a public report format by accident.
- `_contracts.py` still contains low-level validation primitives. This is fine
  while route-private, but promotion should avoid exporting it as a general
  domain library.
- The current primary table is string-valued by design. Notebook computation
  pressure should trigger a separate numeric/dataframe adapter decision.
- The package format remains the tested directory-shaped subset, not a final
  sharing/archive format.
- The writer and workflow prove local ergonomics, but they do not answer
  package acceptance, trust, or durable storage conflict behavior.

## Recommendation

The handoff writer/reader/inspection/workflow vertical was promoted as the
accepted local boundary at this checkpoint. Future handoff work should be
triggered by a named acceptance/import or storage-requirements decision, not by
restating the same route-level conclusions.

The promotion decision is recorded in
[`engineering-prototype-promotion-decision.md`](engineering-prototype-promotion-decision.md).

## Freeze Rule

This readiness note is complete. If a later handoff phase needs its own
readiness assessment, create a new phase-specific readiness note rather than
editing this checkpoint.
