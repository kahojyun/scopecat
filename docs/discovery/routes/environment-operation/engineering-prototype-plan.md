# Environment Operation Engineering Prototype Plan

## Status

Prototype milestone implemented, not an ADR.

This plan starts the engineering prototype for the environment-operation route.
It follows the validated route posture:

```text
approve intent -> execute bounded manager command -> record result -> review locally
```

The first prototype milestone crosses one new authority boundary: Scopecat may
run an already-approved, bounded `uv sync` command through a local subprocess
runner.

The second prototype milestone adds route-local review composition over the
prototype execution result. It does not execute another process or inspect
runtime/package state.

## Implemented Scope

Status: implemented in `scopecat.environment_operation` with injected-runner
tests, a real tiny `uv` success fixture, and a real locked-mode failure
fixture. Execution records promote to typed route-local `UvSyncResult` objects,
which can project local result summaries for downstream review snapshots.

The prototype should support:

- route-local `UvSyncIntent` objects built from validated intent summaries;
- validation that the command is exactly the bounded `uv sync --locked
  --no-default-groups [--group name ...]` shape;
- caller-provided workspace root plus declared relative working directory;
- local subprocess execution with explicit executable path and timeout;
- bounded stdout/stderr summaries with raw output not recorded;
- completed-success, completed-failed, timed-out, and launch-failed execution
  states;
- review findings for failure, timeout, and launch failure;
- route-local `UvSyncResult` objects that carry intent references, bounded
  command results, findings, and explicit policy non-claims;
- route-local result-summary projection from `UvSyncResult` for review
  snapshots and compatibility with discovery-style fixtures;
- route-local operation reviews that align one selected intent with one
  selected typed execution result and surface result or alignment findings;
- explicit non-claims for runtime readiness, dependency-state verification,
  code import/execution, hardware readiness, and run-start permission.

## Still Out Of Scope

This prototype does not:

- parse `pyproject.toml` or `uv.lock`;
- interpret dependency output;
- verify synchronized environments or installed package state;
- probe Python runtimes or virtual environments;
- import, load, or execute selected experiment code;
- run notebooks;
- contact hardware, drivers, firmware utilities, services, or registries;
- decide whether a run is safe, blocked, runnable, reproducible, synced, or
  scientifically valid;
- define a shared manager abstraction for Pixi, Conda, or future managers.

## Stop Condition

Stop this milestone when Scopecat can prepare a route-local intent, execute the
bounded `uv sync` command through an injectable runner, record bounded process
facts, and surface failure/timeout as review findings without claiming runtime
or run readiness. The current prototype satisfies that stop condition and adds
repository-safe real-`uv` fixtures to verify the subprocess success and failure
paths plus typed result, summary projection, and operation-review flows for
downstream review.

The next milestone should be chosen only after this boundary is reviewed. Likely
follow-ups are a post-sync runtime probe, operation review with optional
manifest preflight context, or Pixi-specific pressure before extracting any
shared manager abstraction.
