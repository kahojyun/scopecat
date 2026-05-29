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
- PR/release preparation for this accepted implementation phase;
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

## Acceptance Preflight

The route-local implementation now includes `run_acceptance_preflight(...)` as
the first destination-aware receiving/import check. It consumes a ready
non-mutating import plan, requires an approved preflight request, accepts a
caller-provided storage root plus declared relative destination paths, and
observes only those exact paths for `no_overwrite` collision status.

The preflight can return `ready_for_acceptance_mutation_request` only when the
import plan is ready and declared destinations are available under the observed
storage root. It returns `blocked_by_destination_collision` when a declared
record directory, primary data path, or manifest path already exists,
`blocked_by_destination_guardrail` when destination parent shape would block
the later mutation, and `blocked_before_acceptance_preflight` when the import
plan itself is not ready.

This is still not package acceptance. It does not write records, create
manifests, choose final storage schema, resolve collisions, define rollback,
or import linked-context payloads. It only answers whether a later explicit
mutation request has enough reviewed destination facts to be considered.

The first mutation implementation slice after this preflight is chosen in
[`storage-acceptance-decision.md`](storage-acceptance-decision.md). Keep
rollback and storage-acceptance implementation scope there rather than
expanding this promotion snapshot.

## Storage Acceptance Slice

The route-local implementation now includes `run_storage_acceptance(...)` as
the first narrow storage mutation after a ready acceptance preflight. The
owning scope is
[`storage-acceptance-decision.md`](storage-acceptance-decision.md).

This still does not promote final storage schema, existing-record update,
conflict resolution, crash recovery, archive trust, or linked-context payload
import.

This slice is now implemented and covered as the first mutation checkpoint. It
proves the read-only receiving path can hand off to one explicitly approved
candidate storage write while preserving reviewed package, preflight, and
destination facts across the mutation boundary. It also proves blocked
preflight rejection, destination/root mismatch rejection, no-overwrite file
creation, and best-effort synchronous rollback. Mutation details and rollback
scope are owned by the storage-acceptance decision.

After this slice, the next engineering phase should not broaden mutation
behavior without a new storage or import decision.

## Next Decision Gate

Do not continue by expanding handoff surface area in place. The accepted
implementation boundary now has one complete receiving/import mutation chain:

```text
read-only package open
  -> integrity observation
  -> approved receiving gate
  -> non-mutating import plan
  -> destination acceptance preflight
  -> approved candidate storage acceptance
```

The next engineering phase should choose one explicit path:

- import workflow hardening: define acceptance/rejection UX, review-state
  persistence, and operator-facing error recovery around the existing candidate
  mutation without broadening storage shape;
- storage/archive requirements synthesis: compare the needs from source-root
  package writing, legacy import, existing-record update, source observation,
  package receiving, and running inspection before accepting a storage or
  archive format;
- durable import/storage decision: define conflict policy, existing-record
  update or merge behavior, stronger rollback/crash recovery expectations, and
  the storage API boundary before writing beyond the current candidate layout.

The current workflow is enough to validate local writer/reader/review
ergonomics plus a first explicitly approved candidate storage mutation. It is
not evidence by itself for final storage schema, broad import workflow,
existing-record update, archive format, signatures, authenticity, or
adversarial package trust policy.

## Import Workflow Hardening Slice

The route-local implementation now includes `run_import_workflow(...)` as a
local operator-facing receipt over the accepted receiving/import chain:

```text
acceptance preflight
  -> explicit operator decision
  -> optional approved candidate storage acceptance
  -> local workflow receipt
```

This slice hardens the current candidate workflow without broadening storage
authority. It records approved, rejected, and needs-review operator decisions;
surfaces destination collision, destination guardrail, preflight block, storage
block, and rollback states; and calls the existing storage-acceptance mutation
only when the operator decision is approved.
Rejected and needs-review decisions carry a required single-line
`operator_reason` as local review state. That reason is operator-facing context
for continuing or abandoning the receiving workflow; it is not a package
member, candidate storage manifest field, portable/export artifact, public SDK
contract, or runtime redaction surface.
The companion `summarize_import_workflow_receipt(...)` helper validates a
local workflow receipt and extracts the package id, measurement ids, final
state, next action, and operator reason for operator continuation. It is
read-only: it does not authorize retry, reuse prior preflight facts, reopen
packages, recheck destinations, persist durable review state, or perform
storage mutation.

It does not add final storage schema, conflict resolution, durable review-state
persistence, existing-record update, stronger crash recovery, archive trust,
signatures/authenticity, linked-context payload import, GUI ownership, or a
public import API. Those remain separate reopen triggers.

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
- destination acceptance preflight over exact declared no-overwrite paths;
- narrow storage acceptance mutation with best-effort synchronous rollback;
- local import workflow receipt over explicit approve/reject/needs-review
  operator decisions;
- read-only local import workflow receipt summary for operator continuation;
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
- final storage import API, broad package acceptance workflow, conflict
  policy, or existing-record update;
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
- durable local import beyond the candidate storage acceptance slice,
  especially conflict policy, update/merge behavior, or stronger recovery;
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
