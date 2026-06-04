# Handoff Storage Import Requirements Synthesis

## Status

Historical engineering requirements synthesis.

This note records the requirements synthesis from before durable
Measurement Records creation and durable import existed. It compares the
then-current handoff storage acceptance path with adjacent Measurement Records
storage/import evidence and names what had to wait for the durable creation
flow. It does not accept final storage schema, final import API,
existing-record update behavior, archive format, conflict policy, or shared
measurement-record domain model.

Follow-up decisions: durable measurement-record creation now exists, and the
first durable import/storage boundary is recorded in
[`handoff-durable-import-storage.md`](../prototype-boundaries/handoff-durable-import-storage.md).
Use that document for active import/storage guidance; keep this synthesis as
historical evidence for the pre-durable-import decision pressure.

## Question

After the accepted handoff route proved:

```text
read-only package open
  -> integrity observation
  -> approved receiving gate
  -> non-mutating import plan
  -> destination acceptance preflight
  -> approved candidate storage acceptance
```

what storage/import work is justified before Measurement Records has a
durable creation lifecycle?

## Evidence Compared

At the time of this synthesis, the handoff implementation accepted one
candidate storage mutation in
[`handoff-candidate-storage-acceptance.md`](handoff-candidate-storage-acceptance.md). That slice
requires explicit approval, exact destination fact continuity, no-overwrite
creation, and best-effort synchronous rollback for
`measurement_record_directory_candidate_v0`.

Adjacent Measurement Records evidence adds useful pressure but not final
architecture:

- Legacy import acceptance proves approved copy-into-new-record behavior from
  reviewed adapter-normalized primary data.
- Append-only storage writer proves approved new-record writing from declared
  chunks under caller-provided storage roots.
- Existing-record append update proves one bounded append-segment plus receipt
  mutation under an existing record, without manifest replacement or read-model
  refresh.
- Stored source observation proves read-only checks over one declared
  normalized primary-data file under storage.
- Adapter output boundary proves a logical adapter-produced input boundary
  before import acceptance, without choosing final transport.
- Normalized primary table proves data-level CSV table semantics for
  already-provided normalized bytes, not file observation or storage schema.
- Running measurement inspection proves partial recorded data can be ordinary
  visible state, without accepting final lifecycle, storage, or reader API.

DEC-003 keeps these as separate authority boundaries:
[`../../decisions/architecture/DEC-003-import-source-anti-corruption-boundary.md`](../../decisions/architecture/DEC-003-import-source-anti-corruption-boundary.md).

## Historical Requirements Earned

At the time of this synthesis, any next handoff import/storage work needed to
preserve these requirements:

- Storage mutation stays after read-only package review and explicit operator
  approval.
- Destination identity is caller-declared and compared exactly across
  preflight and mutation. It is not inferred from package paths, source paths,
  fixture paths, or external references.
- Storage-root identity and package-root identity remain continuity facts at
  the mutation boundary.
- `no_overwrite` was the minimum conflict posture for the candidate
  mutation. Silent overwrite, rename, dedupe, or merge behavior is not earned.
- Package primary data, adapter-normalized primary data, stored primary data,
  and external source references remain distinct.
- Linked context remains reference-only unless a later slice accepts one
  concrete payload import/materialization workflow.
- Normalized primary table reading may be adopted by a concrete consumer that
  already has normalized bytes and needs table facts. It should not become
  final storage schema by default.
- Rejection, needs-review, retry review, and receipt summary are local review
  workflow surfaces. They do not authorize mutation without fresh preflight
  and explicit approval.
- Runtime redaction is not added for these local internal summaries. Fixtures
  and expected outputs still need repository-safety review.

## Requirements Not Earned By This Synthesis

This synthesis did not justify implementing these in handoff storage import:

- final record identity allocation;
- final storage schema, storage index, or public storage API;
- import into an existing record;
- manifest replacement, primary-data merge or compaction, read-model refresh,
  or making append segments visible as primary data;
- conflict policy beyond no-overwrite blocking;
- stale-lock cleanup, lock identity, concurrent writer behavior, crash
  recovery, or transactional durability;
- archive extraction, external authenticity, trust policy, or adversarial
  package-root handling;
- linked-context payload import or recursive relation traversal;
- GUI-owned import review state or durable cross-session review persistence;
- shared measurement-record lifecycle or domain model.

## What Could Happen Before Record Creation

Before a durable Measurement Records creation lifecycle existed, the useful
work was requirements-level and guardrail-level:

- compare the accepted storage/import slices and keep their authority
  boundaries explicit;
- name the preconditions any future final import/storage decision must satisfy;
- keep the handoff candidate mutation small and route-local;
- improve local review ergonomics around the existing candidate mutation
  without adding storage authority;
- adopt normalized table reading only at concrete read/preview consumers that
  already own normalized data access.

This was enough to prevent accidental promotion of candidate layouts into final
architecture. It was not enough to implement final import/storage mutation.

## What Had To Wait For Record Creation

These decisions needed to wait until the measurement-record creation flow was
designed or being implemented:

- how durable record IDs are allocated;
- how new, in-progress, partial, complete, failed, or review-needed records are
  represented;
- whether package import creates a new record, attaches to a created shell,
  updates an existing record, or offers multiple choices;
- how storage manifests, append receipts, read models, and primary data relate
  after updates;
- what the conflict policy is for existing destination records or imported
  package measurements;
- which recovery guarantees apply after process failure or concurrent storage
  mutation;
- which API owns durable import review state across sessions.

Without those decisions, handoff import stopped at candidate storage
acceptance plus local review receipts.

## Next Gate

This synthesis originally named two possible gates:

- Measurement-record creation lifecycle: define durable record identity,
  initial storage state, lifecycle/progress state, and creation failure
  semantics. The prototype-start decision is recorded in
  [`measurement-records-creation-lifecycle.md`](../prototype-boundaries/measurement-records-creation-lifecycle.md).
- Durable import/storage decision: after creation semantics exist, define how
  package acceptance creates or updates records, what conflict policy applies,
  and what recovery guarantees are required.

The first gate is now implemented by the Measurement Records prototype line.
The second gate is now decided by
[`handoff-durable-import-storage.md`](../prototype-boundaries/handoff-durable-import-storage.md).

Do not implement broader handoff storage import as an incremental extension of
`measurement_record_directory_candidate_v0`. Treat that layout as historical
evidence for the candidate mutation only.
