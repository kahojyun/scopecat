# Managed Code Version Validation Result

## Status

Fixture validation result with managed-code-version summary candidate, not an
ADR.

This result records what the first managed code-version fixture proved and
where the boundary remains intentionally narrow.

## Fixture

- `tests/fixtures/managed_code_version/basic_record/`
- `implementation_candidates/managed_code_version/`

The fixture validates a first managed-version boundary:

- a captured code-version record can become a Scopecat-managed record;
- managed identity can be assigned without deciding final object ID or backend
  layout;
- file inventory can stay exactly aligned with the source record include list;
- notebook source-without-outputs policy can carry into the managed record;
- per-file checksum, size, and observation time can be represented as
  integrity hints;
- materialization intent can be recorded without creating a workspace;
- environment restoration, selected-version loading, code import, execution,
  Git inspection, archive creation, and workflow/DAG semantics remain out of
  scope.

## Boundary Confirmed

Scopecat can represent a recorded code version before it can restore or run
that version.

The useful first managed boundary is:

- source captured code-version record;
- assigned stable managed-version identity;
- included file inventory;
- recorded form for each file;
- content-integrity hints;
- declared materialization intent;
- explicit non-restore, non-environment, and non-execution claims.

This follows
[`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md):
managed workspace storage pressure can start with a record-shaped summary while
storage, restore, sync, environment, loading, execution, merge, and GUI
behavior remain deferred.

## Summary Candidate

The implementation candidate checks that the managed-version record can be
produced mechanically from explicit fixture input without adding filesystem,
Git, environment, or execution authority.

It assembles and validates:

- captured code-version record summaries;
- managed code versions with stable identity, status, storage authority, file
  counts, integrity hint counts, and materialization intent;
- file inventory records with relative source and materialization paths;
- referential integrity from managed version to source record;
- exact inclusion alignment between source-record scope and file records;
- SHA-256-prefixed integrity hints;
- attention items for record-only storage, integrity hints, deferred
  materialization, no environment restoration, no code execution, and no Git
  inspection.

The builder remains side-effect free. It does not read source files, inspect
Git state, create archives, restore environments, materialize workspaces,
import code, execute code, or define workflow/DAG contracts.

## Relationship To Prior Slices

The fixture depends on the code-recording slice for captured code-version record
vocabulary. In that vocabulary, the run/step code record defines the capture
scope for a point-in-time code version/snapshot; later selection can choose,
promote, or restore that record. The fixture also keeps selected measurement
export pressure in view by using package- or workspace-relative
materialization paths, but it does not accept export package writer behavior.

The fixture uses integrity-hint vocabulary that resembles external-file
observed state. That resemblance is design pressure only; it does not earn a
shared integrity model or storage schema.

## Remaining Risks

- final storage backend remains undecided;
- archive, content-addressed store, or Git-backed implementation remains
  undecided;
- the first capture mechanism that writes file contents is still unvalidated;
- integrity hint freshness, recomputation, and mismatch behavior remain
  undecided;
- materializing a version into an editable workspace remains unvalidated;
- comparing current editable code with a managed version remains unvalidated;
- environment readiness likely needs a later active validation slice;
- GUI language for save, restore, compare, and use-version actions remains
  undecided.

## Current Recommendation

Use this fixture and summary candidate as the first managed code-version
record boundary.

The next implementation-shaped step should stay adjacent: either validate
selected-version comparison against a current editable folder or validate
workspace materialization intent. Environment restoration should wait until a
managed storage/materialization boundary has more implementation pressure.
