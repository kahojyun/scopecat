# Environment Operation Engineering Prototype Readiness

## Status

Engineering prototype readiness note, not an ADR.

This is the current implementation-boundary checkpoint for the
environment-operation vertical until a separate promotion or next-stage
decision exists. Update it when the accepted boundary, deferred boundary, or
recommended next decision gate changes. Keep routine API inventory in
[`../../../scopecat/environment_operation/README.md`](../../../scopecat/environment_operation/README.md)
and leave the prototype plan as a frozen scope snapshot.

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
if any prototype output is promoted into a portable/export artifact.

## Readiness Judgment

The environment-operation engineering prototype has completed the first
execution/review boundary and now includes a bounded post-sync runtime probe
milestone.

The accepted prototype target is the first route-local execution vertical:

```text
validated uv sync intent summary
  -> route-local UvSyncIntent
  -> approved local uv subprocess execution
  -> UvSyncExecutionRecord
  -> route-local UvSyncResult
  -> route-local operation review
  -> route-local UvRuntimeProbeIntent
  -> approved local uv runtime probe execution
  -> route-local UvRuntimeProbeResult
  -> route-local UvSyncOperationRun workflow summary
```

`UvSyncResult.to_summary()` remains a one-way route-local review-snapshot
projection for fixture snapshots and edge inspection. The internal review API
consumes the typed result object instead of a raw dictionary summary.

This does not promote the full environment-operation route, a public SDK,
runtime readiness, package-state verification, experiment-code execution,
hardware readiness, or a shared environment-manager abstraction.

## Stop Criteria Check

| Criterion | Status | Assessment |
| --- | --- | --- |
| Route-local product-shaped API | Met | The route-local sync, result/review projection, runtime-probe, and composed workflow surface exists under `scopecat.environment_operation`; keep the live API list in the module README. |
| Actual external interaction boundary | Met | The prototype runs bounded `uv sync` commands through `SubprocessUvRunner` with caller-provided workspace root, relative cwd, explicit executable path, and timeout. |
| Representative success and failure coverage | Met | Tests cover injected sync success/failure/timeout/launch-failure behavior, real tiny `uv` success and missing-lock failure fixtures, runtime-probe process failure/timeout/launch failure, invalid JSON, output-shape rejection, raw-output rejection, non-virtual-environment findings, and a real post-sync probe fixture. |
| Review projection and non-claims | Met | Execution records promote to typed local results, which project local result summaries and feed operation reviews with bounded output, findings, alignment checks, and explicit no runtime-readiness/package-state/code-execution claims. |
| Post-sync runtime probe | Met | `UvRuntimeProbeIntent.from_sync_result(...)`, `execute_uv_runtime_probe(...)`, and `UvRuntimeProbeResult.to_summary(...)` record bounded interpreter facts via `uv run --locked --no-sync` without environment repair, package-state verification, experiment-code execution, or run-readiness claims. |
| Green repository verification | Met | Current milestone verification uses `uv run python -m unittest discover -s tests` and `uv run prek run --all-files`. |

## Keep As Implementation Shape

These choices are strong enough to carry into PR review:

- route-local `scopecat/environment_operation/` module boundary;
- no runtime dependency on historical `implementation_candidates`;
- `UvSyncIntent` as the first route-local approved command object;
- bounded argv shape, currently `uv sync --locked --no-default-groups` plus
  optional `--group name` pairs;
- caller-provided workspace root plus declared relative command directory;
- injected command runner for tests and `SubprocessUvRunner` with explicit
  absolute `uv_executable` for real local execution;
- bounded stdout/stderr summaries with raw output not recorded;
- explicit execution states for success, failure, timeout, and launch failure;
- review findings instead of run-blocking or readiness decisions;
- route-local typed result, result-summary projection, and operation-review
  flow.
- route-local runtime probe intent/result objects derived from successful sync
  results;
- bounded runtime probe argv shape, currently
  `uv run --locked --no-sync python -c <stdlib probe>`;
- interpreter fact capture for Python version, implementation, executable,
  prefix, base prefix, and virtual-environment status.
- route-local `run_uv_sync_operation(...)` composition that executes approved
  sync, reviews the typed result, conditionally probes only successful
  review-clean sync results, and records skipped probe state explicitly.

## Keep Deferred

These are not blockers for this PR:

- installed package or virtual-environment state verification;
- runtime readiness beyond bounded interpreter fact capture;
- parsing `pyproject.toml`, `uv.lock`, or uv dependency output;
- dependency graph interpretation or package-change summaries;
- code import, notebook execution, or experiment-code execution;
- hardware, driver, service, registry, or control-PC probing;
- Pixi, Conda, or shared manager abstractions;
- optional manifest preflight context inside route-local operation review;
- final public SDK names, CLI, GUI, or workflow/DAG integration.

## Discovery Candidate Posture

Existing environment-operation implementation candidates remain historical
discovery evidence. They validated intent, declared external result recording,
and review-bundle composition before Scopecat owned process execution.

This prototype intentionally fills the missing execution boundary between
approved intent and result review. Do not rewrite old discovery candidates only
to match the prototype shape. Update them only if preserving historical tests
requires it, or if a future route extension explicitly chooses one as evidence.

## Recommendation

Keep this PR focused on the approved `uv sync` execution/review boundary plus
the bounded post-sync runtime probe. After rebasing onto the latest
`origin/main`, the branch should be ready for review once repository
verification remains green.

Future environment-operation work should be triggered by a new boundary
question: broader review-bundle integration with optional manifest or
prepared-context references, package-state pressure, Pixi/Conda pressure, or
selected experiment-code execution. Those should be separate PRs, not
additional broadening of this prototype line.

## Update Rule

Do not update this note for every internal helper, private module, or API
spelling change. Update it only when the implementation boundary, non-claims,
or next decision gate changes. If environment-operation receives a later
promotion decision, move the canonical accepted-boundary language there and
freeze this readiness note as the checkpoint that ended the prototype line.
