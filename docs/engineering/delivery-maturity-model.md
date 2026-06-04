# Delivery Maturity Model

## Status

Project engineering governance.

## Purpose

This document defines how Scopecat classifies delivery maturity for
product-facing scopes as discovery work moves toward production behavior. It is
not a strict project-wide phase gate: different user journeys, workflows, use
cases, vertical slices, and capabilities may sit at different maturity levels at
the same time.

Use this model before promoting discovery work into implementation or before
expanding an engineering prototype.

Use [`terminology.md`](terminology.md) when a change needs to distinguish
user journey, workflow, use case, scenario, operation, capability, maturity,
validation method, decision status, evidence, artifact boundary, and ownership.

This model manages maturity for delivery objects:

- user journeys;
- workflows;
- use cases;
- production vertical slices;
- product capabilities.

Scenarios and operations can provide evidence for maturity, but they do not own
delivery maturity by themselves.

The default rule is:

```text
discovery evidence
  -> named use case, workflow, user journey, or capability question
  -> scenario or operation evidence when needed
  -> chosen validation method
  -> engineering prototype when live route-local behavior is needed
  -> production vertical slice
  -> production readiness
  -> maintained product capability
```

Candidate-summary parity is not progress by itself. It becomes useful evidence
when it closes a named use case, workflow seam, capability risk, or product risk
in [`workflow-validation-map.md`](workflow-validation-map.md) or
[`../product/target-capabilities.md`](../product/target-capabilities.md).

## Maturity Owners

Track delivery progress by maturity owner, not by the number of candidates,
fixtures, scenarios, operations, or prototypes.

| Maturity Owner | Use For |
| --- | --- |
| User journey | A broad end-to-end user path across one or more capabilities. |
| Workflow | A user-visible sequence of activities that completes a goal. Workflows expose missing seams and next validation questions. |
| Use case | A scoped user goal or workflow segment that can be validated independently. |
| Vertical slice | A scoped end-to-end product path that proves one workflow through one or more capabilities. |
| Product capability | A product ability that can support one or more workflows, such as Measurement Records, Handoff Packages, or Parameter State Review. Capabilities are the main owner for maturity and maintenance. |

## Evidence Scopes

These scopes may appear in validation maps, fixtures, tests, and prototype
boundaries. They provide evidence for a maturity owner, but they are not
maturity owners by themselves.

| Evidence Scope | Use For | Maturity Relationship |
| --- | --- | --- |
| Scenario | A concrete validation, review, or acceptance situation. | Supports a use case, workflow, or capability maturity claim. |
| Operation | A single approved action, command, mutation, or read/projection run. | Supports a use case, workflow step, technical-risk, or capability maturity claim. |
| Step | One activity inside a workflow or use case. | Can be validated, but should not be tracked as an independent maturity owner unless it becomes a use case. |
| Module | The code organization that implements behavior. | Owns implementation details; it does not own product maturity. |

## Maturity States

| Maturity | Purpose | Exit Criteria | Typical Deliverables |
| --- | --- | --- | --- |
| Discovery | Understand the problem, user job, workflow pressure, and evidence-backed boundaries. | The next question is specific enough to test with a candidate, prototype, or explicit deferral. | Problem briefs, owner-local validation notes when needed, repository-safe fixtures, expected outputs. |
| Engineering prototype | Validate production-shaped route-local behavior for one use case, workflow step, workflow seam, capability risk, or technical risk. Scenario and operation evidence may be used, but they do not become maturity owners. | The prototype has a clear entrypoint, typed or explicit contracts, workflow/failure tests, and a documented boundary. | `src/scopecat/<route>/`, module README, route-local typed objects, acceptance/failure tests, local review artifacts. |
| Production vertical slice | Deliver one end-to-end user workflow from entrypoint to durable state or output with defined failure behavior. | The slice can be used as a coherent product path and has acceptance tests, compatibility expectations, and documented user-visible behavior. | Owned module, acceptance/scenario tests, storage/output authority docs, route decision, compatibility and failure rules. |
| Production readiness | Prepare a vertical slice for reliable use beyond prototype conditions. | Operational, compatibility, migration, diagnostics, documentation, and support risks are reviewed and either closed or explicitly accepted. | Readiness checklist, release criteria, compatibility notes, migration/upgrade notes, diagnostic expectations. |
| Maintained product capability | Maintain a stable capability inside the Scopecat product. A capability may support multiple user workflows; it is not a separate product. | Changes are handled through normal product maintenance: compatibility, regression coverage, support expectations, and documented deprecation or migration when needed. | User docs, support policy, compatibility guarantees, migration/upgrade notes, operational diagnostics. |

## Validation Methods

Validation methods are tools for moving a maturity owner forward. They are not
project progress metrics by themselves.

Common methods include:

- discovery interview, workflow mapping, or problem brief;
- fixture-based validation plan or result;
- technical spike;
- implementation candidate;
- production-shaped engineering prototype;
- scripted scenario or dogfood run;
- acceptance/scenario/failure test;
- production-readiness review.

Choose the method that answers the current risk. Early discovery may prefer
fixtures and candidates; production readiness prefers scenario tests,
diagnostics, compatibility review, migration review, and user-facing docs.

## Promotion Rules

Before moving a concept into `src/scopecat/` or treating it as an accepted
prototype boundary, update or reference:

- [`workflow-validation-map.md`](workflow-validation-map.md), to name the user
  journey, workflow, use case, seam, or evidence scope;
- [`../product/target-capabilities.md`](../product/target-capabilities.md), to name the
  product capability, maturity, evidence, and advancement question;
- [`implementation-register.md`](implementation-register.md), to name the live
  implementation owner and route readers to detailed module and boundary docs;
- the owning module README or prototype-boundary note, to define the accepted
  boundary and live API.

Promotion changes the work item from exploration to managed scope. After a
prototype boundary is accepted, future work on that route should be one of:

- maintenance on the accepted boundary;
- promotion toward a named production vertical slice;
- a separately named use case, workflow, or seam prototype.

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

Artifact-boundary labels are required when repository safety, portability,
publicness, or redaction behavior affects implementation or review. Ordinary
internal governance, architecture, and route-navigation documents usually do
not need those labels.

Prefer the precise terms from [`terminology.md`](terminology.md). For example,
call a candidate, spike, prototype, fixture validation, or dogfood run a
validation method; call repository-safe, local/review, portable/export, or
public output an artifact boundary; call proposed, accepted, superseded, or
retired choices decision status.

Shared models, shared relation schemas, and reusable platform abstractions need
a separate decision. They should not be extracted from one accepted route just
because the names look reusable.

## Drift Control

When an AI-assisted session proposes a new implementation slice, first classify
the work:

- new discovery evidence;
- validation method output, such as candidate parity or candidate cleanup;
- engineering prototype for a named use case, workflow seam, capability risk, or
  technical risk;
- production vertical slice;
- production readiness;
- maintenance on a product capability.

If the work cannot be tied to a maturity owner, update the workflow and use case
map or narrow the validation question before promoting code.
