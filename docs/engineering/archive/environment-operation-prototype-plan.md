# Environment Operation Engineering Prototype Plan

## Status

Frozen engineering prototype plan.

This document records the prototype objective, scope, non-claims, and stop
conditions that launched the environment-operation engineering vertical. Do
not update it to mirror routine API additions. Current implementation-boundary
guidance lives in
[`environment-operation-prototype-readiness.md`](environment-operation-prototype-readiness.md);
the current route-local Python surface lives in
[`../../../src/scopecat/environment_operation/README.md`](../../../src/scopecat/environment_operation/README.md).

This plan started the engineering prototype for the environment-operation route.
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

The third prototype milestone adds a post-sync interpreter fact probe using
`uv run --locked --no-sync python -c ...`. It records bounded Python runtime
facts after a successful sync result without repairing the environment,
verifying package state, importing experiment code, or deciding run readiness.

## Still Out Of Scope

This prototype does not:

- parse `pyproject.toml` or `uv.lock`;
- interpret dependency output;
- verify synchronized environments or installed package state;
- verify full Python runtime readiness beyond the bounded interpreter fact
  probe;
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
or run readiness.

Stop the post-sync runtime probe milestone when Scopecat can derive a bounded
probe intent from a successful sync result, run `uv run --locked --no-sync`
through an injectable runner, record bounded interpreter facts, and surface
failure/system-Python signals as review findings without claiming package state
or run readiness.

The next milestone should be chosen only after this boundary is reviewed. Likely
follow-ups are operation review with optional manifest/prepared-context
references, package-state pressure, selected experiment-code import pressure,
or Pixi-specific pressure before extracting any shared manager abstraction.

## Freeze Rule

This plan is complete. If a later environment-operation phase needs its own
scope, fixture policy, or stop criteria, create a phase-specific plan rather
than expanding this snapshot.
