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

Execution records can be projected into a route-local result summary for later
review composition. That projection carries the selected intent reference,
bounded command result, result findings, and explicit non-claims. It remains a
local review surface, not a runtime-readiness result.

It does not read or parse `pyproject.toml`, read or parse `uv.lock`, interpret
dependency output, verify installed package state, probe Python runtimes, import
selected experiment code, execute notebooks, contact hardware, or decide that a
run can start.

## API Surface

Current user-facing prototype surface:

- `UvSyncIntent.from_summary(...)`;
- `execute_uv_sync(...)`;
- `UvSyncExecutionRecord.to_result_summary(...)`;
- `SubprocessUvRunner`;
- route projection objects exported from `scopecat.environment_operation`.

Modules with leading underscores are route-private implementation modules.
They may be tested directly while the prototype hardens, but they are not
public SDK or cross-route domain APIs.
