# Engineering Terminology

## Status

Engineering terminology guide.

## Purpose

Use standard software-engineering terms where possible. Scopecat-specific terms
should name a concrete project concept, not merge planning, evidence,
architecture, artifact policy, and code ownership into one word. Prefer common
product and software-delivery vocabulary over project-local category names.

## Preferred Terms

| Concept | Preferred Term | Use For | Avoid Using For |
| --- | --- | --- | --- |
| Broad user path | User journey | A user's end-to-end path across one or more workflows or capabilities. | Code modules, fixture families, or implementation-candidate counts. |
| Ordered user process | Workflow | A user-visible sequence of activities that completes a goal. | A single operation, route-local receipt, code module, or capability. |
| Product ability | Capability | A product ability that may support one or more workflows. | A separate product, a route-local module name, or a validation method. |
| Delivery maturity | Maturity | Discovery, engineering prototype, production vertical slice, production readiness, or maintained product capability for user journeys, workflows, use cases, vertical slices, and product capabilities. | Project-wide phase gates, validation method counts, scenarios, operations, modules, or artifact boundaries. |
| Validation technique | Validation method | Candidate, spike, prototype, scenario, dogfood run, fixture validation, or readiness review. | Product progress unless it advances a named maturity owner. |
| Implementation location | Module | Code package or module that implements behavior. | Product capability unless the product concept and code boundary intentionally match. |
| Formal choice | Decision | A committed engineering or product choice with owner, scope, and supersession path. | Discovery evidence, validation result, or navigation note. |
| Evidence strength | Evidence | Research result, validation result, test, fixture, scenario, or dogfood run supporting a claim. | Decision status or implementation ownership. |
| Artifact classification | Artifact boundary | Repository-safe fixture, local/review artifact, portable/export artifact, or public documentation. | Product strategy, workflow maturity, or route status. |

## Product Scope Terms

Use these terms from largest to smallest scope:

| Term | Use For | Do Not Mix With |
| --- | --- | --- |
| User journey | A broad end-to-end user path across one or more product capabilities, such as moving selected measurement data between computers. | A single API call, storage mutation, or route-local receipt. |
| Workflow | A user-visible sequence of activities that completes a goal. Use this only when order, state, and handoff between steps matter. | Code modules, implementation candidates, or evidence counts. |
| Use case | A scoped user goal or workflow segment that can be validated independently. | Product capability ownership. |
| Scenario | A concrete situation used for validation, review, or acceptance testing. | A stable product capability or broad user journey. |
| Operation | A single approved action, command, mutation, or read/projection run. | User workflow or capability maturity. |
| Step | One activity inside a workflow or use case. | A standalone product object. |

When a map must mention multiple scopes together, separate them by section or
include an explicit `Level` column using the standard terms above. Do not invent
new taxonomy names when `user journey`, `workflow`, `use case`, `scenario`,
`operation`, or `step` is accurate enough.

## Stable IDs

Use stable IDs only for cross-document owners that need durable references.
Titles may change, but IDs should not be reused.

| Prefix | Owner | Use For |
| --- | --- | --- |
| `JNY-*` | [`../product/target-journeys.md`](../product/target-journeys.md) | Target user journeys. |
| `UC-*` | [`workflow-validation-map.md`](workflow-validation-map.md) | Use cases and workflow segments that can drive vertical-slice validation. |
| `UC-CAND-*` | [`workflow-validation-map.md`](workflow-validation-map.md) | Candidate use cases that may become `UC-*` after validation. |
| `CAP-*` | [`../product/target-capabilities.md`](../product/target-capabilities.md) | Accepted product capabilities. |
| `CAND-*` | [`../product/target-capabilities.md`](../product/target-capabilities.md) | Candidate feature areas that are not product capabilities yet. |
| `DEC-*` | [`../decisions/register.md`](../decisions/register.md) | Durable product, architecture, engineering, discovery, or operational decisions. |
| `BR-RISK-*` | [`../brownfield/risk-register.md`](../brownfield/risk-register.md) | Brownfield risks that need ongoing management. |
| `EV-*` | [`../evidence/evidence-register.md`](../evidence/evidence-register.md) | Stable evidence claims. |

Cross-document references may include `ID + short label` in headings or first
mentions when the label helps readers orient themselves. In compact tables,
prefer ID-only references when the column name and owner document make the
object type clear. Do not copy canonical names, definitions, maturity, status,
scope, or rationale into non-owner documents.

Do not assign stable IDs to scenarios, operations, fixtures, modules, roadmap
steps, or discovery files unless they are promoted into one of the owner types
above.

## Decision Status

Use decision status only for documents that actually make or preserve a
decision.

| Status | Meaning |
| --- | --- |
| Proposed | Suggested but not accepted. |
| Accepted | Current decision for the named scope. |
| Superseded | Replaced by a newer decision or owner. |
| Retired | Kept for history; not active guidance. |
| No decision | The document is evidence, synthesis, navigation, or policy vocabulary rather than a decision. |

Prefer positive status labels over repeated negative templates. For example:

```text
Status: Discovery synthesis
Decision status: No decision
```

is clearer than describing the same file by what it is not.

Use [`../decisions/README.md`](../decisions/README.md) for decision-record
types, ADR usage, and the current decision register.

## Scope Language

Use the narrowest standard phrase:

- `Supported behavior` for what code or product behavior currently does.
- `Out of scope` for product or module boundaries.
- `Did not validate` for validation results.
- `Decision status` for whether a document commits to a choice.
- `Artifact boundary` for repository safety, redaction, portability, or public
  output behavior.

Avoid using `posture` as a generic term. Keep it only when a historical document
already uses it or when the phrase names a specific product stance. Prefer
`boundary`, `classification`, `maturity`, `decision status`, or `strategy`
when those are more precise.

## Ownership Language

Separate ownership questions:

- product ownership: which workflow or capability is being advanced;
- implementation ownership: which module owns live behavior;
- document ownership: which document is the durable source of truth;
- artifact ownership: which boundary controls fixture, review, portable/export,
  or public output behavior.

Do not use `accepted`, `promoted`, or `owner` without saying which of these
questions is being answered.
