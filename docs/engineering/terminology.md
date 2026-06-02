# Engineering Terminology

## Status

Engineering terminology guide.

## Purpose

Use standard software-engineering terms where possible. Scopecat-specific terms
should name a concrete project concept, not merge planning, evidence,
architecture, artifact policy, and code ownership into one word.

## Preferred Terms

| Concept | Preferred Term | Use For | Avoid Using For |
| --- | --- | --- | --- |
| User path | Workflow | A user's end-to-end goal and the steps needed to complete it. | Code modules, fixture families, or implementation-candidate counts. |
| Product ability | Capability | A product ability that may support one or more workflows. | A separate product, a route-local module name, or a validation method. |
| Delivery maturity | Maturity | Discovery, engineering prototype, production vertical slice, production readiness, or maintained product capability. | Project-wide phase gates or validation method counts. |
| Validation technique | Validation method | Candidate, spike, prototype, scenario, dogfood run, fixture validation, or readiness review. | Product progress unless it advances a named workflow or capability. |
| Implementation location | Module | Code package or module that implements behavior. | Product capability unless the product concept and code boundary intentionally match. |
| Formal choice | Decision | A committed engineering or product choice with owner, scope, and supersession path. | Discovery evidence, validation result, or navigation note. |
| Evidence strength | Evidence | Research result, validation result, test, fixture, scenario, or dogfood run supporting a claim. | Decision status or implementation ownership. |
| Artifact classification | Artifact boundary | Repository-safe fixture, local/review artifact, portable/export artifact, or public documentation. | Product strategy, workflow maturity, or route status. |

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
