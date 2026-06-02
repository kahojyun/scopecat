# Environment Operation Engineering Prototype Promotion Decision

## Status

Engineering promotion decision, not an ADR.

This is the canonical environment-operation implementation-boundary note for
the first route-local execution vertical. Update this file when an accepted
boundary or next decision gate changes. Keep live API syntax in
[`../../../src/scopecat/environment_operation/README.md`](../../../src/scopecat/environment_operation/README.md)
and leave the prototype plan/readiness notes as frozen snapshots.

## Decision

Promote the environment-operation engineering prototype as the accepted
baseline for the route's first local `uv` execution/review vertical:

```text
validated uv sync intent summary
  -> route-local UvSyncIntent
  -> approved local uv subprocess execution
  -> UvSyncExecutionRecord
  -> route-local UvSyncResult
  -> route-local operation review
  -> optional route-local UvRuntimeProbeIntent
  -> approved local uv runtime probe execution
  -> route-local UvRuntimeProbeResult
  -> route-local UvSyncOperationRun workflow summary
```

This promotion stops the current broad environment-operation prototype line.
Further work on the same route should be either:

- small maintenance on the accepted local `uv` execution/review vertical;
- PR/release preparation for this accepted implementation phase;
- a separately scoped route extension triggered by the next decision gate
  below.

It should not continue as broad prototype expansion.

## Accepted Baseline

The promoted baseline includes:

- the route-local `src/scopecat/environment_operation/` module boundary;
- no runtime dependency on historical `implementation_candidates`;
- `UvSyncIntent` as the approved route-local command object parsed from a
  validated discovery-style intent summary;
- bounded sync argv construction, currently
  `uv sync --locked --no-default-groups` plus optional `--group name` pairs;
- caller-provided workspace root plus declared relative command directory;
- injected command runners for tests and `SubprocessUvRunner` with an explicit
  absolute `uv_executable` for real local execution;
- empty child-process environment unless a later decision accepts explicit
  environment-variable handling;
- bounded stdout/stderr summaries with raw output not recorded;
- explicit execution states for success, failure, timeout, and launch failure;
- `UvSyncResult.from_execution(...)` as the typed route-local promotion from
  execution record to reviewable result;
- `UvSyncResult.to_summary()` as a one-way local review-snapshot projection for
  fixtures and edge inspection;
- route-local operation review over typed `UvSyncIntent` and `UvSyncResult`
  objects, with findings rather than run-blocking or readiness decisions;
- optional post-sync runtime probe intent/result objects derived only from a
  successful sync result;
- bounded runtime probe argv construction, currently
  `uv run --locked --no-sync python -c <stdlib probe>`;
- interpreter fact capture for Python version, implementation, executable,
  prefix, base prefix, and virtual-environment status;
- `run_uv_sync_operation(...)` as the local composition that executes approved
  sync, reviews the typed result, conditionally probes successful review-clean
  sync results, and records skipped probe state explicitly.

The prepared-run route now consumes `EnvironmentOperationReview` as optional
prior evidence through a prepared-run-owned projection adapter. That
integration does not change environment-operation ownership: this route still
owns intent/result/review semantics, manager scope, process-execution records,
runtime probe eligibility, and non-readiness claims.

## Explicit Non-Promotions

This decision does not promote:

- the full environment-operation route;
- public SDK names, package publishing metadata, CLI, GUI, or workflow/DAG
  integration;
- runtime readiness, run permission, run safety, reproducibility, or hardware
  readiness decisions;
- installed package or virtual-environment state verification beyond the
  bounded interpreter facts captured by the runtime probe;
- parsing `pyproject.toml`, parsing `uv.lock`, dependency graph
  interpretation, or package-change summaries;
- experiment-code import, selected-code execution, notebook execution, or
  generated-artifact regeneration;
- hardware, driver, service, registry, control-PC, firmware, or lab backend
  probing;
- arbitrary process execution, open-ended command execution, cancellation UI,
  approved environment variables, or richer process supervision;
- Pixi, Conda, or a shared manager abstraction;
- portable/export projection of local cwd, interpreter paths, stdout/stderr
  snippets, or operation review summaries;
- a shared environment, prepared-run, experiment-code, or measurement-record
  domain model.

## Discovery Candidate Posture

Existing environment-operation implementation candidates remain historical
discovery evidence. They validated intent construction, declared external
result recording, optional manifest preflight, and review-bundle composition
before Scopecat owned local process execution.

The promoted implementation fills the missing execution boundary between an
approved route-local intent and result review. Do not rewrite old discovery
candidates only to match this promoted shape. Update them only if preserving
historical tests requires it, or if a future route extension explicitly chooses
one as evidence.

## Next Decision Gate

Do not continue by expanding environment-operation surface area in place. The
accepted implementation boundary now has one complete local execution/review
chain:

```text
approved uv sync intent
  -> bounded uv sync subprocess execution
  -> typed result and operation review
  -> optional bounded post-sync interpreter probe
  -> composed local workflow summary
```

The next engineering phase should choose one explicit path:

- operation-review integration: add optional manifest preflight to the
  route-local operation review without turning it into a sync prerequisite;
- runtime-readiness review: validate package-state observation, selected
  experiment-code import, or run-readiness decisions separately from the
  current interpreter fact probe;
- manager expansion: validate Pixi- or Conda-specific intent/result/probe
  pressure before extracting shared manager contracts;
- execution-wrapper hardening: validate cancellation, executable selection,
  approved environment variables, richer output capture, or failure
  classification as a separate process-authority decision;
- handoff continuity: validate reference-only experiment context package
  projection before packaging code, environment artifacts, or runnable restore
  behavior.

The current workflow is enough to validate local approved `uv sync` execution,
bounded result review, and a first post-sync interpreter fact probe. It is not
evidence by itself for runtime readiness, package-state truth, selected-code
execution, multi-manager architecture, portable handoff projection, or a
general process executor.
