# Project Phase Model

## Status

Project engineering governance.

## Purpose

This document defines the engineering maturity stages used when discovery work
moves toward production code. Use it before promoting discovery work into
implementation or before expanding an engineering prototype.

The default rule is:

```text
discovery evidence
  -> named workflow question
  -> implementation candidate or engineering prototype
  -> production vertical slice
  -> production readiness
  -> maintained product capability
```

Candidate-summary parity is not promotion evidence unless it closes a named
workflow step, workflow seam, or risk question in
[`workflow-validation-map.md`](workflow-validation-map.md).

## Phase Responsibilities

| Phase | Purpose | Exit Criteria | Typical Deliverables |
| --- | --- | --- | --- |
| Discovery | Understand the problem, user job, workflow pressure, and evidence-backed boundaries. | The next question is specific enough to test with a candidate, prototype, or explicit deferral. | Problem briefs, route notes, validation plans/results, repository-safe fixtures, expected outputs. |
| Implementation candidate | Explore a narrow implementation shape quickly, usually against discovery fixtures. | The candidate either answers the question and is ready for promotion, or remains historical evidence. | `implementation_candidates/`, spikes, candidate tests, expected summaries. |
| Engineering prototype | Validate a production-shaped route-local behavior for one workflow step, workflow seam, or technical risk. | The prototype has a clear entrypoint, typed or explicit contracts, workflow/failure tests, and a documented boundary. | `src/scopecat/<route>/`, module README, route-local typed objects, workflow acceptance tests, local review artifacts. |
| Production vertical slice | Deliver one end-to-end user workflow from entrypoint to durable state or output with defined failure behavior. | The slice can be used as a coherent product path and has acceptance tests, compatibility expectations, and documented user-visible behavior. | Owned module, acceptance/scenario tests, storage/output authority docs, route decision, compatibility and failure rules. |
| Production readiness | Prepare a vertical slice for reliable use beyond prototype conditions. | Operational, compatibility, migration, diagnostics, documentation, and support risks are reviewed and either closed or explicitly accepted. | Readiness checklist, release criteria, compatibility notes, migration/upgrade notes, diagnostic expectations. |
| Maintained product capability | Maintain a stable capability inside the Scopecat product. A capability may support multiple user workflows; it is not a separate product. | Changes are handled through normal product maintenance: compatibility, regression coverage, support expectations, and documented deprecation or migration when needed. | User docs, support policy, compatibility guarantees, migration/upgrade notes, operational diagnostics. |

## Promotion Rules

Before moving a concept into `src/scopecat/` or treating it as an accepted
prototype boundary, update or reference:

- [`workflow-validation-map.md`](workflow-validation-map.md), to name the user
  workflow, seam, or risk question;
- [`vertical-slice-register.md`](vertical-slice-register.md), to name the
  implementation owner, entrypoint, tests, fixtures, and scope boundary;
- the owning module README or prototype-boundary note, to define the accepted
  boundary and live API.

Promotion changes the work item from exploration to managed scope. After a
prototype boundary is accepted, future work on that route should be one of:

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

Artifact posture labels are required when repository safety, portability,
publicness, or redaction behavior affects implementation or review. Ordinary
internal governance, architecture, and route-navigation documents usually do
not need those labels.

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
- production readiness;
- maintenance on a product capability.

If the work cannot be classified, update the workflow map or narrow the
validation question before promoting code.
