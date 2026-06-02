# Handoff Engineering Prototype Plan

## Status

Frozen engineering prototype plan, not accepted architecture.

This document is a historical plan snapshot. Do not update it to mirror every
new promoted API. Current accepted implementation boundaries live in
[`handoff.md`](../boundaries/handoff.md);
current exported API details live in
[`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md).

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
src/scopecat/handoff/
  __main__.py
  _contracts.py
  _manifest_preview.py
  inspect.py
  opener.py
  package.py
  read_only.py
  tables.py
```

The implementation now lives in `src/scopecat/handoff/` as part of the local
installable package. This keeps the route boundary explicit while leaving
research fixtures and implementation candidates outside the package.

Low-level helpers may be reused from existing implementation candidates only
when their semantics already match the handoff route. New shared helpers should
remain route-local unless at least two concrete implementation consumers need
the same behavior, failure semantics, and tests.

## Outcome

The plan answered the intended engineering question: a route-local
`src/scopecat/handoff/` boundary can carry the handoff package reader/review
workflow without promoting a shared measurement-record domain model, final
package/archive format, final storage schema, GUI architecture, dataframe
dependency, or production plotting stack.

This section intentionally does not list every promoted API. Maintain the
current accepted boundary in the promotion decision and the current exported
surface in the module README.

Promotion follow-up decisions resolved by
[`handoff.md`](../boundaries/handoff.md):

- leading-underscore helper modules stay route-private;
- static HTML remains the first local review surface;
- numeric conversion, dataframe adapters, and plotting-library integration
  remain deferred until a concrete notebook or GUI workflow requires them.

## Fixture Policy

Discovery fixtures and expected outputs remain validation evidence. Prototype
fixtures become engineering regression assets.

The promoted writer fixtures live under
`tests/fixtures/prototypes/handoff/handoff_engineering_prototype_writer/` and
use source-root terminology directly. The older discovery candidate writer
fixtures remain under `tests/fixtures/handoff_package_writer/` as historical
evidence for the candidate shape and are not translated in promoted writer
tests.

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
uv run ruff check .
uv run ruff format --check .
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
[`handoff-prototype-readiness.md`](handoff-prototype-readiness.md);
the promotion decision is recorded in
[`handoff.md`](../boundaries/handoff.md).

## Remaining Follow-Up Questions

- Which old implementation candidates can be archived, left untouched as
  evidence, or ignored by future maintenance after branch merge?
- Which decision path should resume next: package receiving/import acceptance,
  or storage/archive requirements synthesis across multiple slices?
- If receiving/import resumes first, what is the acceptance boundary before
  durable storage writes, conflict policy, rollback, and trust behavior?
- If storage/archive resumes first, which existing slices are sufficient to
  decide the minimum directory/archive/storage contract?
