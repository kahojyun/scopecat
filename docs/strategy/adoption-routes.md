# Adoption Routes

## Status

Provisional route-definition owner.

This document names product-value route hypotheses so the progress tracker does
not become a hidden strategy document or backlog. These routes are not a
roadmap, capability map, subsystem map, implementation order, or product
acceptance claim.

## Purpose

Preserve route hypotheses only when they help current `JC` selection avoid
overfitting to one slice. A route is durable enough to live here only when it
names standalone user value that could be adopted progressively.

The canonical `JC` candidate wording, evidence basis, and boundaries still live
in [`../evidence/inventory.md`](../evidence/inventory.md). The tracker owns
phase and coordination only.

## Route Hypotheses

| Route hypothesis | Touched `JC` rows | Standalone value being tested |
| --- | --- | --- |
| Run history and analysis handoff | `JC-001`, `JC-002`, `JC-006`, `JC-015` | Open, understand, reopen, select, package, and later trace measurement work without replacing acquisition code. |
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Explain copied notebooks, scripts, static entrypoint evidence, user-code snapshots, known-good sources, drift, and readiness before any deployment, code-version loader, or managed-runner capability is accepted. |
| Experiment intent and readiness | `JC-007`, `JC-008`, `JC-016` | Current route hypothesis starts with reviewable intent and outcome reports; strong adoption payoff likely requires continuation behavior such as resume, retry, review continuation, or selected remeasurement before managed execution or broader runtime ownership is considered. |
| Calibration and parameter memory | `JC-003`, `JC-011`, `JC-012`, `JC-016` | Start with replacing mutable parameter files through drift queries, branch or working-point history, run linkage, direct-update checkpoints, and bad-state labeling/exclusion before separating proposal/review, apply, or mutation-ownership decisions. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. |
| Analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Trace figures, fits, reports, and claims back to source runs, processing choices, corrections, exclusions, and ambiguity. |

## Cross-Route Constraints

Same-station data access is not a standalone route yet. Preserve it as an
validation constraint on run explanation, analysis handoff, and durable reopen:
stable opaque `record_id`, legacy source refs, machine-specific locations, and
read capabilities should let another same-station computer resolve historical
records without treating the control-PC path as identity. Shared folders are a
baseline for simple file-based systems, but they should not define record
identity. Live observation and remote execution remain later scope.

## Promotion Rule

Keep runtime ownership, managed execution, code registry, automatic version
management, proposal workflow, and similar solution-shaped names out of
adoption routes by default. Treat them as capability hypotheses; promote only
pain-framed routes after accepted journey evidence or user validation shows
standalone value, and after any required ADR or safety decision.

Use the owning evidence and fixture docs for detailed corrective stance:
[`../evidence/inventory.md`](../evidence/inventory.md) owns `JC` candidate
wording and boundaries, while
[`../evidence/pain-discovery-fixtures.md`](../evidence/pain-discovery-fixtures.md)
owns current fixture questions and support levels.

Routes may guide journey selection and cross-journey review. They do not own
contracts, implementation boundaries, API schemas, storage models, hardware
safety assumptions, or `JC` acceptance.

Move a route toward product acceptance only after accepted journeys or user
validation show that the route itself is a durable product direction and that
the user-facing workflow return justifies adopting the route, including any
required rewrite of route-owned experiment code.
