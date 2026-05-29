# Handoff Storage Import Requirements Synthesis

## Status

Engineering requirements synthesis, not an ADR.

This note compares current handoff storage acceptance with adjacent
Measurement Records storage/import evidence. It names what can be decided
before the durable measurement-record creation flow exists, and what must wait
for that flow. It does not accept final storage schema, final import API,
existing-record update behavior, archive format, conflict policy, or shared
measurement-record domain model.

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
if any future output is promoted into a portable/export artifact.

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

The current handoff implementation accepts one candidate storage mutation in
[`storage-acceptance-decision.md`](storage-acceptance-decision.md). That slice
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

The route-level synthesis in
[`../../discovery/routes/measurement-records/README.md`](../../discovery/routes/measurement-records/README.md)
and
[`../../discovery/routes/measurement-records/import-source-decision.md`](../../discovery/routes/measurement-records/import-source-decision.md)
keeps these as separate authority boundaries.

## Requirements Earned Now

Any next handoff import/storage work should preserve these requirements:

- Storage mutation stays after read-only package review and explicit operator
  approval.
- Destination identity is caller-declared and compared exactly across
  preflight and mutation. It is not inferred from package paths, source paths,
  fixture paths, or external references.
- Storage-root identity and package-root identity remain continuity facts at
  the mutation boundary.
- `no_overwrite` is the minimum conflict posture for current candidate
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

## Requirements Not Earned Yet

The current evidence does not justify implementing these in handoff storage
import now:

- final record identity allocation;
- final storage schema, storage index, or public storage API;
- import into an existing record;
- manifest replacement, primary-data merge or compaction, read-model refresh,
  or making append segments visible as primary data;
- conflict policy beyond no-overwrite blocking;
- stale-lock cleanup, lock identity, concurrent writer behavior, crash
  recovery, or transactional durability;
- archive extraction, signatures, authenticity, trust policy, or adversarial
  package-root handling;
- linked-context payload import or recursive relation traversal;
- GUI-owned import review state or durable cross-session review persistence;
- shared measurement-record lifecycle or domain model.

## What Can Happen Before Record Creation

Before a durable Measurement Records creation lifecycle exists, the useful work
is requirements-level and guardrail-level:

- compare the accepted storage/import slices and keep their authority
  boundaries explicit;
- name the preconditions any future final import/storage decision must satisfy;
- keep the handoff candidate mutation small and route-local;
- improve local review ergonomics around the existing candidate mutation
  without adding storage authority;
- adopt normalized table reading only at concrete read/preview consumers that
  already own normalized data access.

This is enough to prevent accidental promotion of candidate layouts into final
architecture. It is not enough to implement final import/storage mutation.

## What Should Wait For Record Creation

These decisions should wait until the measurement-record creation flow is
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

Without those decisions, handoff import should continue to stop at candidate
storage acceptance plus local review receipts.

## Next Gate

The next implementation phase should choose one of two named gates:

- Measurement-record creation lifecycle: define durable record identity,
  initial storage state, lifecycle/progress state, and creation failure
  semantics.
- Durable import/storage decision: after creation semantics exist, define how
  package acceptance creates or updates records, what conflict policy applies,
  and what recovery guarantees are required.

Do not implement broader handoff storage import as an incremental extension of
`measurement_record_directory_candidate_v0`. Treat that layout as evidence for
the current candidate mutation only.
