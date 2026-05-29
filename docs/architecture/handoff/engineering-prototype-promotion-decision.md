# Handoff Engineering Prototype Promotion Decision

## Status

Engineering promotion decision, not an ADR.

This is the canonical handoff implementation-boundary note. Update this file
when an accepted boundary or next decision gate changes. Keep live API syntax
in [`../../../scopecat/handoff/README.md`](../../../scopecat/handoff/README.md)
and leave the prototype plan/readiness notes as frozen snapshots.

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
if any accepted implementation output is later promoted into a
portable/export artifact.

## Decision

Promote the handoff engineering prototype as the accepted baseline for the
handoff route's first local implementation vertical:

```text
caller-provided source root
  -> source-root package writer
  -> directory-shaped package subset
  -> manifest validation and preview classification
  -> read-only package open
  -> package, measurement, table, declared plot, linked-context, and finding access
  -> local CLI, static HTML review surface, or local workflow receipt
```

This promotion stops the current engineering prototype line. Further work on
the same route should be either:

- small maintenance on the accepted local handoff vertical;
- PR/release preparation for the current branch;
- a separately scoped route extension triggered by the reopen conditions in
  [`decision.md`](../../discovery/routes/measurement-records/handoff/decision.md).

It should not continue as broad prototype expansion.

## Source-Root Writer Extension

The next promoted route-local extension is a package writer that starts from a
caller-provided `source_root` plus declared relative paths for normalized
primary data. This deliberately replaces the discovery candidate's
storage-root wording at the accepted API boundary: the writer can validate and
copy source files without accepting final Scopecat storage architecture.
Promoted regression fixtures now use the source-root policy directly; the old
storage-root writer candidate fixture remains only as discovery evidence and a
negative compatibility check at the promoted boundary.

The accepted writer behavior is narrow:

- require an approved package write request and no-overwrite collision policy;
- parse raw write-request dictionaries into route-local write-source objects at
  the API boundary;
- copy only declared primary CSV data after sha256 and size preflight;
- write the current directory-shaped package subset and deterministic manifest;
- keep linked context reference-only;
- return a local write receipt;
- prove generated packages open through the accepted read-only reader.

This extension still does not promote archive format, package import or
acceptance, final storage schema, signatures/authenticity, linked-context
payload packaging, or a shared measurement-record domain model.

## Local Workflow Composition

The accepted route also exposes a narrow local workflow composition:
`run_package_workflow(...)` runs the promoted source-root writer, reopens the
written package with the promoted reader, and can optionally write the local
inspection HTML artifact outside the package tree.

This is not a new package lifecycle decision. It proves writer/reader/review
ergonomics while continuing to defer archive format, package import or
acceptance, final storage schema, signatures/authenticity, and package
integrity verification.

## Read-Only Integrity Gate

The route-local implementation now includes
`observe_package_integrity(package_dir)` as the first receiving/import
prerequisite. It reuses the promoted manifest validation boundary, collects
manifest-declared package members, and compares package-local regular files to
paired digest and size facts where present.

This observation can produce `declared_integrity_verified`,
`integrity_review_required`, or `integrity_observed_with_undeclared_members`.
It is intentionally read-only and does not verify signatures, authenticity,
transport provenance, archive contents, import acceptance, or storage
mutation.

## Read-Only Receiving Gate

The route-local implementation also includes `run_receiving_gate(...)` as the
approved review gate before any import/acceptance mutation. It opens the
package, observes integrity, requires `approval_state: approved`, and checks
reviewed package id, preview classification, and integrity classification
against observed facts.

This gate can return `ready_for_acceptance_mutation` only when reviewed facts
match and integrity is `declared_integrity_verified`. It can also return
`blocked_before_acceptance` for reviewed packages that still need integrity
review. The gate is read-only and intentionally accepts no destination,
storage-root, selected-measurement materialization, or conflict-policy fields.

## Non-Mutating Import Plan

The route-local implementation now includes `run_import_plan(...)` as the
first post-gate receiving/import planning artifact. It composes read-only
package open, optional local inspection artifact generation, the receiving
gate, and a non-mutating plan over selected package measurements.

The plan can become `ready_for_import_acceptance_decision` only when the
receiving gate is ready for acceptance mutation. It lists package-local
primary data members and linked-context reference handling for a later
acceptance decision, while leaving destination record identity, storage
schema, conflict policy, acceptance mutation, and rollback policy explicitly
unassigned. If the receiving gate is blocked, the plan records
`blocked_before_import_acceptance` and does not produce measurement import
actions.

This is a planning boundary, not an import implementation. It still does not
promote storage mutation, package acceptance, archive extraction, conflict
detection, final storage schema, rollback behavior, signatures/authenticity,
or linked-context payload import.

## Next Decision Gate

Do not continue by expanding handoff surface area in place. After the
read-only receiving gate and non-mutating import plan, the next engineering
phase should choose one
explicit path:

- package receiving/import acceptance: define acceptance, rejection, conflict,
  review, and rollback boundaries for an inbound package before writing into
  any durable storage location;
- storage/archive requirements synthesis: compare the needs from source-root
  package writing, legacy import, existing-record update, source observation,
  package receiving, and running inspection before accepting a storage or
  archive format.

The current workflow is enough to validate local writer/reader/review
ergonomics plus non-mutating receiving/import planning. It is not evidence by
itself for final storage schema, import acceptance, archive format,
signatures, authenticity, or adversarial package trust policy.

## Accepted Baseline

The promoted baseline includes:

- the route-local `scopecat/handoff/` module boundary;
- `open_package(package_dir)` as the Python entrypoint;
- `python -m scopecat.handoff <package-dir>` as the local CLI entrypoint;
- route-private manifest validation and preview classification;
- typed route-local manifest fragments after raw JSON/dict validation;
- product-shaped route projections for package, measurement, tables, declared
  plot series, findings, and linked context;
- read-only package-local primary CSV opening for `preview_ready`
  measurements;
- declared preview metadata as the preview authority;
- package-id and package-directory continuity;
- canonical primary-data topology,
  `measurements/{measurement_record_id}/primary.csv`;
- linked context as visible reference-only review state;
- local static HTML as the first review artifact;
- non-mutating import planning after a ready receiving gate;
- representative regression coverage over basic and route-pressure fixtures.

## Explicit Non-Promotions

This decision does not promote:

- final public SDK names or package publishing metadata;
- hard pandas/numpy dependency;
- matplotlib, production plotting, or publication-grade rendering;
- live GUI components, routing, or interaction model;
- numeric dtype conversion, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- archive extraction, compressed package format, signatures, authenticity,
  trust policy, or adversarial package-root race handling;
- storage import, acceptance, conflict policy, or existing-record update;
- linked-context payload packaging, opening, recursive traversal, or import;
- analysis/fit result model, fit execution, uncertainty, write-back, or result
  import;
- shared measurement-record domain model or cross-route object lifecycle.

## Discovery Candidate Posture

Existing handoff implementation candidates remain historical discovery
evidence. They should not be treated as runtime dependencies for the promoted
local handoff vertical.

Do not rewrite old candidate validation results only to match the promoted
implementation shape. Update old candidates only when preserving their
historical tests requires it, or when a future route extension explicitly
chooses to reuse one as evidence.

## Maintenance Rule

Future changes to the accepted local handoff vertical should preserve the current
boundary:

- raw JSON/dict handling stays at the manifest/package boundary;
- route-private modules with leading underscores are not public SDK or
  cross-route domain APIs;
- runtime redaction is required only at declared or effective portable/export
  boundaries;
- static HTML remains a local review surface, not a public report format;
- external dependencies require a concrete workflow trigger.

## Resume Triggers

Resume handoff work only when a named workflow needs one of the deferred
capabilities, such as:

- notebook computation requiring numeric/dataframe adapters;
- GUI review requiring interaction beyond static HTML;
- external sharing requiring archive/signature/trust behavior;
- durable local import requiring storage acceptance and conflict policy;
- inspectable linked-context payloads;
- analysis or fit results becoming first-class read-only display facts;
- another route needing identical lifecycle and failure semantics, justifying
  a narrower shared-model decision.

## Verification

Promotion was made after the engineering readiness assessment in
[`engineering-prototype-readiness.md`](engineering-prototype-readiness.md) and
should be preserved with:

```text
uv run python -m unittest discover -s tests
uv run prek run --all-files
```
