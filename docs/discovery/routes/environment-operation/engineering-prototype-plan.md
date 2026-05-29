# Environment Operation Engineering Prototype Plan

## Status

Prototype milestone in progress, not an ADR.

This plan starts the engineering prototype for the environment-operation route.
It follows the validated route posture:

```text
approve intent -> execute bounded manager command -> record result -> review locally
```

The first prototype milestone crosses one new authority boundary: Scopecat may
run an already-approved, bounded `uv sync` command through a local subprocess
runner.

## First Milestone

Status: implemented in `scopecat.environment_operation` with injected-runner
tests and a real tiny `uv` workspace fixture.

The prototype should support:

- route-local `UvSyncIntent` objects built from validated intent summaries;
- validation that the command is exactly the bounded `uv sync --locked
  --no-default-groups [--group name ...]` shape;
- caller-provided workspace root plus declared relative working directory;
- local subprocess execution with explicit timeout;
- bounded stdout/stderr summaries with raw output not recorded;
- completed-success, completed-failed, timed-out, and launch-failed execution
  states;
- review findings for failure, timeout, and launch failure;
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
one repository-safe real-`uv` fixture to verify the subprocess path.

The next milestone should be chosen only after this boundary is reviewed. Likely
follow-ups are a post-sync runtime probe, additional execution-result hardening
against real manager failures, or Pixi-specific pressure before extracting any
shared manager abstraction.
