# Handoff Engineering Prototype Promotion Decision

## Status

Accepted engineering-prototype boundary.

This is the current live route-local boundary note for the handoff prototype.
Update this file when an accepted boundary or next decision gate changes. Keep
live API syntax in
[`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
and leave the prototype plan/readiness notes as frozen snapshots.

Historical candidate-storage checkpoints for the older
`measurement_record_directory_candidate_v0` route remain evidence for review
order, approval, local receipts, and rollback pressure, but they are no longer
the active durable Measurement Records handoff import path. Current durable
import ownership lives in
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md);
historical details live in
[`handoff-candidate-storage-acceptance.md`](../archive/handoff-candidate-storage-acceptance.md)
and
[`handoff-storage-import-requirements-synthesis.md`](../archive/handoff-storage-import-requirements-synthesis.md).

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
- a separately scoped route extension triggered by this note's resume triggers
  or by the durable import decision.

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

The current durable import implementation is a separate accepted boundary:
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).
That path adapts exactly one ready import-plan measurement into the
Measurement Records durable import pipeline. Keep destination storage mutation,
new-record import receipts, rollback classification, and retry review in that
durable-import boundary rather than expanding this read-only package-use note.

## Historical Candidate Context

The older candidate-storage route proved that the read-only receiving path
could hand off to an explicitly approved candidate storage mutation while
preserving reviewed package, destination, local receipt, and rollback evidence.
That path used destination acceptance preflight, candidate storage acceptance,
and local import-workflow receipts over approve/reject/needs-review operator
decisions.

Those details are archived because the current durable import path no longer
writes the candidate layout directly. Durable receiving work now adapts
reviewed package facts into Measurement Records durable import through
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).

The local CLI still supports read-only package orientation and receipt-summary
review:

```text
python -m scopecat.handoff <package-dir>
python -m scopecat.handoff --receipt-summary <receipt.json>
```

The CLI does not run package import, approve storage acceptance or durable
import, persist review state, or become a public import API.

## Accepted Baseline

The promoted local package-use baseline includes:

- the route-local `src/scopecat/handoff/` module boundary;
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
- read-only local receipt summaries for operator continuation;
- read-only retry review for both historical candidate receipts and current
  durable handoff-import receipts;
- local CLI receipt-summary mode for operator continuation review;
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
- existing-record update, broad package acceptance workflow, durable
  multi-measurement batch import, or conflict policy beyond the current
  durable new-record no-overwrite behavior;
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

Future changes to the accepted local package-use vertical should preserve the
current boundary:

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
- durable local import beyond the current single-measurement new-record route,
  especially existing-record update, batch import, conflict policy beyond
  no-overwrite, update/merge behavior, or stronger recovery;
- inspectable linked-context payloads;
- analysis or fit results becoming first-class read-only display facts;
- another route needing identical lifecycle and failure semantics, justifying
  a narrower shared-model decision.

## Verification

Promotion was made after the engineering readiness assessment in
[`prototype-readiness.md`](../archive/handoff-prototype-readiness.md) and
should be preserved with:

```text
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```
