# Environment Operation Prototype Module

Engineering prototype module for approved local environment-manager operations.

This module is route-local prototype code. It tests a production-shaped Python
entrypoint over validated environment-operation discovery candidates without
accepting final manager abstraction, runtime readiness, code execution,
hardware readiness, workflow/DAG behavior, or GUI architecture.

The first milestone executes one bounded `uv sync` command from a previously
approved intent summary. It validates the workspace root and relative command
directory, runs the command through a subprocess runner, records bounded output
summaries, and returns a review-oriented execution record.

Real subprocess execution requires either an injected runner or an explicit
absolute `uv_executable`. The subprocess runner uses that executable path for
the child process and passes an empty child environment. The approved intent
shape still does not accept arbitrary environment-variable overrides.

Execution records can be promoted into a typed route-local `UvSyncResult` for
later review composition. `UvSyncResult.to_summary()` projects that object into
a local review snapshot carrying the selected intent reference, bounded command
result, result findings, and explicit non-claims. The summary remains a local
review surface, not a runtime-readiness result.

Route-local operation reviews compose one selected `UvSyncIntent` with one
selected `UvSyncResult`. They surface alignment mismatches and result findings
as review items without deciding run permission or runtime readiness.

The runtime probe milestone builds a bounded `UvRuntimeProbeIntent` from one
successful `UvSyncResult`, then runs `uv run --locked --no-sync python -c ...`
to collect small interpreter facts. The probe records whether Python reported a
virtual environment, but it does not repair the environment, inspect packages,
import experiment code, or decide run readiness.

It does not read or parse `pyproject.toml`, read or parse `uv.lock`, interpret
dependency output, verify installed package state, import selected experiment
code, execute notebooks, contact hardware, or decide that a run can start.

## API Surface

Current user-facing prototype surface:

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
- `SubprocessUvRunner`;
- route projection objects exported from `scopecat.environment_operation`.

Modules with leading underscores are route-private implementation modules.
They may be tested directly while the prototype hardens, but they are not
public SDK or cross-route domain APIs.
