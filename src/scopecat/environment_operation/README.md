# Environment Operation Module

## Status

Current engineering-prototype implementation owner for approved local
environment-manager operations.

The promoted boundary is owned by
[`../../../docs/engineering/prototype-boundaries/environment-operation.md`](../../../docs/engineering/prototype-boundaries/environment-operation.md).
Implementation ownership is tracked in
[`../../../docs/engineering/implementation-register.md`](../../../docs/engineering/implementation-register.md).

## Purpose

Capture bounded environment-manager operation evidence for later review
without deciding runtime readiness, importing experiment code, contacting
hardware, or starting a run.

The current route validates one approved `uv sync` operation plus an optional
bounded interpreter fact probe. It records review-oriented facts that later
workflows can consume as prior evidence.

## Current Surfaces

Approved sync execution:

- builds one `UvSyncIntent` from a previously approved summary;
- validates the workspace root and relative command directory;
- runs bounded `uv sync` through an injected runner or explicit absolute
  `uv_executable`;
- passes an empty child environment and does not accept arbitrary environment
  overrides;
- records bounded output summaries in an execution record.

Operation review:

- promotes execution records into typed route-local `UvSyncResult` objects;
- projects local review summaries with selected intent reference, bounded
  command result, result findings, and explicit non-claims;
- composes one selected intent with one selected result in
  `EnvironmentOperationReview`;
- surfaces alignment mismatches and result findings without deciding run
  permission or runtime readiness.

Runtime probe:

- builds `UvRuntimeProbeIntent` from one successful sync result;
- runs `uv run --locked --no-sync python -c ...` through the same bounded
  execution path;
- records small interpreter facts, including whether Python reported a virtual
  environment;
- returns a skipped probe state when sync failed, review findings exist, or the
  caller disables probing.

## API Surface

Current route-local surface:

- `UvSyncIntent.from_summary(...)`;
- `execute_uv_sync(..., uv_executable=...)` or `execute_uv_sync(..., runner=...)`;
- `UvSyncResult.from_execution(...)`;
- `UvSyncResult.to_summary(...)`;
- `UvSyncExecutionRecord.to_result_summary(...)` as a compatibility projection;
- `review_uv_sync_operation(...)`;
- `UvRuntimeProbeIntent.from_sync_result(...)`;
- `execute_uv_runtime_probe(..., uv_executable=...)` or
  `execute_uv_runtime_probe(..., runner=...)`;
- `UvRuntimeProbeExecutionRecord.to_result(...)`;
- `UvRuntimeProbeResult.to_summary(...)`;
- `run_uv_sync_operation(...)`;
- `UvSyncOperationRun.to_summary(...)`;
- `SubprocessUvRunner`;
- route projection objects exported from `scopecat.environment_operation`.

Modules with leading underscores are route-private implementation modules.
They may be tested directly while the route-local implementation hardens, but
they are not public SDK or cross-route domain APIs.

## Artifact Boundaries

Result, review, operation-run, and probe summaries are local review surfaces.
They are not portable/export artifacts unless a later slice explicitly promotes
one.

Runtime probe summaries may include local interpreter paths such as
`sys.executable`, `sys.prefix`, `sys.base_prefix`, and the local execution cwd.
Those path facts are local review facts only. A portable/export promotion would
need a separate artifact boundary and redaction decision.

## Tests And Fixtures

Module behavior is covered by repository `unittest` tests under `tests/` and
small repository-safe fixtures under `tests/fixtures/*environment*` and
`tests/fixtures/prototypes/environment_operation/`.

## Active Non-Goals

This module does not currently own:

- final manager abstraction or multi-manager behavior;
- parsing `pyproject.toml`, parsing `uv.lock`, interpreting dependency output,
  or verifying installed package state;
- runtime-readiness decisions or run permission;
- selected experiment-code import, notebook execution, or managed runner
  behavior;
- hardware readiness, hardware probing, or service operation;
- GUI architecture or production UI workflow.
