# Environment Operation Discovery Track

## Status

Discovery track index with accepted engineering-prototype handoff.

The live implementation boundary is owned by
[`../../../engineering/prototype-boundaries/environment-operation.md`](../../../engineering/prototype-boundaries/environment-operation.md)
and
[`../../../../src/scopecat/environment_operation/README.md`](../../../../src/scopecat/environment_operation/README.md).
This discovery note is historical evidence orientation, not a live API
inventory.

## Discovery Conclusion

The validated environment-operation posture is:

```text
approve intent -> record result -> review locally
```

The accepted prototype is intentionally `uv`-specific. Scopecat may construct
bounded approved `uv sync` intent, run the accepted local sync/probe vertical,
record typed process facts, and project local review summaries. `uv` remains
authoritative for dependency resolution, lockfile semantics, synchronization,
installation, and package-manager behavior.

Environment operation records can support prepared-run and declared-environment
review by explaining what command was approved, what result was recorded, and
how that result aligns with selected context. They do not make environment
state the anchor record and do not grant run-start, runtime readiness, code
execution, package-state truth, or hardware authority.

## Carry Forward

Keep these concepts available for future work:

- explicit operation approval and managed request/result identifiers;
- bounded manager-specific argv construction rather than arbitrary command
  execution;
- relative command working directory and selected context continuity checks;
- typed local process result facts with bounded stdout/stderr summaries;
- post-sync interpreter fact probing as review evidence only;
- local operation review findings instead of run-blocking or readiness claims;
- manager-specific validation before any shared manager abstraction.

## Not Earned

Do not infer these from the discovery route or current prototype:

- shared environment schema or shared manager interface;
- dependency graph interpretation, package-state truth, or installation truth;
- Conda/Pixi/non-Python manager semantics;
- experiment-code import, loading, execution, or managed runner behavior;
- runtime readiness, hardware readiness, run permission, or run blocking;
- portable/export package projection for environments.

## Historical Evidence

Use the compact slice inventory for removed validation-result bodies:

- [`../../archive/slice-inventory.md`](../../archive/slice-inventory.md)

The frozen engineering milestone notes remain historical snapshots:

- [`../../../engineering/archive/environment-operation-prototype-plan.md`](../../../engineering/archive/environment-operation-prototype-plan.md)
- [`../../../engineering/archive/environment-operation-prototype-readiness.md`](../../../engineering/archive/environment-operation-prototype-readiness.md)

## Reopen Triggers

Reopen this discovery track only when a named product or engineering question
needs new evidence:

- manifest preflight becomes part of the accepted execution review path;
- users need runtime-readiness decisions rather than interpreter fact review;
- Pixi, Conda, or another manager needs manager-specific pressure testing;
- handoff packages need reference-only environment context projection;
- Scopecat starts coordinating run lifecycle beyond the current sync/probe
  review vertical.

Do not add another environment-operation slice merely to restate `uv`
ownership, local review-summary posture, dependency-sync non-claims, or shared
manager deferral.
