# UV Sync Result Candidate

This candidate records one declared external `uv sync` result and checks it
against a prior bounded command intent.

Summary posture: `review_summary`. The output is a result-recording summary,
not dependency resolution, dependency sync verification, package-install
verification, process execution, runtime compatibility, hardware readiness,
run-start readiness, or a portable/public/export artifact.

It can:

- validate a declared prior `uv_sync_intent` summary projection;
- validate a bounded external result record with execution state, exit code,
  timestamp/duration consistency, command argv, relative command cwd, nullable
  local execution cwd, observer, and bounded stdout/stderr summaries;
- require stdout and stderr to be summary-only review text while raw output is
  not recorded;
- compare result manager, operation, relative command cwd, and argv against the
  prior approved intent and report mismatches as review findings;
- report success, failure, not-run, or mismatch status without parsing uv
  output or inspecting environment state.

`working_directory` is the approved command directory used for intent/result
comparison and remains relative to the editable workspace contract earned by
`uv_sync_intent`. `local_execution_cwd` is nullable local-review evidence from
the external executor; it may preserve an absolute local path and is not a
portable/public/export projection.

It does not spawn subprocesses, run `uv`, inspect the filesystem, read
`pyproject.toml`, read `uv.lock`, parse manifests or lockfiles, parse uv output
into dependency facts, resolve dependencies, verify synchronized package
state, inspect installed packages or runtimes, import or execute code, probe
hardware, define a shared environment-manager abstraction, define managed
runner behavior, make run-blocking decisions, or decide that a run can start.

The candidate uses slice-local dataclass contracts. These contracts are not a
shared environment schema and are not a Pixi/Conda-capable manager interface.
Future Pixi/Conda-capable managers should earn separate manager-specific intent
and result slices before any shared manager abstraction is extracted.
