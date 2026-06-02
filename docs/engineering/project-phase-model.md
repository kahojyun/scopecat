# Project Phase Model

## Status

Project engineering governance.

## Purpose

This document defines what each project phase is allowed to prove and what
artifacts it may own. Use it before promoting discovery work into implementation
or before expanding an engineering prototype.

The default rule is:

```text
discovery evidence
  -> named workflow question
  -> engineering prototype or vertical slice
  -> accepted implementation owner
```

Candidate-summary parity is not promotion evidence unless it closes a named
workflow step, workflow seam, or risk question in
[`workflow-validation-map.md`](workflow-validation-map.md).

## Phase Responsibilities

| Phase | Owns | Does Not Own | Typical Artifacts |
| --- | --- | --- | --- |
| Discovery | Problem framing, user jobs, boundary pressure, candidate contracts, small explicit fixtures, and validation results. | Live architecture, production module ownership, public SDK shape, final schema, or production support promises. | Problem briefs, route notes, validation plans/results, repository-safe fixtures, expected outputs. |
| Implementation candidate | Implementation-shaped exploration that proves a narrow candidate behavior against discovery fixtures. | Accepted route ownership, runtime dependency for live modules, public APIs, or broad shared abstractions. | `implementation_candidates/`, spikes, candidate tests, expected summaries. |
| Engineering prototype | A production-shaped route-local boundary around one user workflow, workflow seam, or explicit risk question. | Final public API, shared domain model, full GUI, workflow/DAG engine, broad platform abstraction, or production support promise. | `src/scopecat/<route>/`, module README, route-local typed objects, workflow acceptance tests, local review artifacts. |
| Production vertical slice | A scoped user workflow that closes from entrypoint to durable state or output with defined failure behavior. | Unvalidated adjacent workflows, broad product platform, generic shared model, or public/export behavior not explicitly accepted. | Owned module, acceptance/scenario tests, storage/output authority docs, route decision, compatibility and failure rules. |
| Production supported | A maintained workflow with support, diagnostics, compatibility, upgrade, and user-facing expectations where relevant. | New discovery claims without evidence or unscoped cross-route expansion. | User docs, support policy, compatibility guarantees, migration/upgrade notes, operational diagnostics. |

## Promotion Rules

Before moving a concept into `src/scopecat/` or treating it as an accepted
prototype boundary, update or reference:

- [`workflow-validation-map.md`](workflow-validation-map.md), to name the user
  workflow, seam, or risk question;
- [`vertical-slice-register.md`](vertical-slice-register.md), to name the
  implementation owner, entrypoint, tests, fixtures, and non-goals;
- the owning module README or prototype-boundary note, to define the accepted
  boundary and live API.

Promotion should stop broad prototype expansion. After a prototype boundary is
accepted, future work on that route should be one of:

- maintenance on the accepted boundary;
- promotion toward a named production vertical slice;
- a separately named workflow or seam prototype.

## Code, Test, And Fixture Rules

Discovery code and implementation candidates may depend on discovery fixtures,
but live route modules should not depend on historical candidate modules unless
a promotion decision explicitly accepts that dependency.

Engineering prototypes should test workflow behavior and failure behavior, not
only expected JSON parity. Dictionary-shaped edge adapters are acceptable for
compatibility with existing fixtures, but route-local internals should use
typed objects or equivalent explicit contracts.

Production vertical slices must define:

- the user entrypoint or caller authority;
- the durable state or output artifact authority;
- no-overwrite, rollback, blocked, or failure behavior where mutation occurs;
- the boundary for fixtures, expected outputs, generated review artifacts, and
  portable/export/package artifacts when the slice creates or changes them;
- the regression tests or scenario tests that prove the accepted workflow.

Do not require artifact posture labels on ordinary internal governance,
architecture, or route-navigation documents. Boundary classification is for
artifacts whose repository safety, portability, publicness, or redaction
behavior affects implementation or review.

Shared models, shared relation schemas, and reusable platform abstractions need
a separate decision. They should not be extracted from one accepted route just
because the names look reusable.

## Drift Control

When an AI-assisted session proposes a new implementation slice, first classify
the work:

- new discovery evidence;
- candidate parity or candidate cleanup;
- engineering prototype for a named workflow/seam/risk;
- production vertical slice;
- maintenance on an accepted owner.

If the work cannot be classified, do not promote code. Update the workflow map
or ask for a narrower validation question first.
