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
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Explain copied notebooks, scripts, selected entrypoints, user-code snapshots, code-version selection pressure, known-good sources, drift, and readiness before any deployment or managed-runner capability is accepted. |
| Experiment intent and readiness | `JC-007`, `JC-008`, `JC-016` | Preview, diff, freeze, and validate helper-authored grouped calibration intent with local execution, shared-resource conflict hints, review gates, resume/remeasure markers, and outcome reports before any managed execution or broader runtime ownership is considered. |
| Calibration and parameter memory | `JC-003`, `JC-011`, `JC-012`, `JC-016` | Query parameter drift, branches, run linkage, prior-version retry, direct-update history, declared-context, and advisory evidence before any proposal/review, apply, or mutation-ownership decision. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. |
| Analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Trace figures, fits, reports, and claims back to source runs, processing choices, corrections, exclusions, and ambiguity. |

## Promotion Rule

Keep runtime ownership, managed execution, code registry, automatic version
management, proposal workflow, and similar solution-shaped names out of
adoption routes by default. Treat them as capability hypotheses; promote only
pain-framed routes after accepted journey evidence or user validation shows
standalone value, and after any required ADR or safety decision.

Current corrective stance:

- `JC-008` should validate helper-authored batch intent plus a minimal local
  executor and outcome report for bounded grouped calibration, not a managed
  runner.
- `JC-003` should start from parameter memory, drift, branches, run linkage,
  prior-version retry, direct-update history, and bad-state handling;
  explicit proposal/review is optional future scope.
- `JC-016` remains a capability hypothesis until lower-level local execution,
  explicit recording, parameter memory, stop behavior, runtime owner, and audit
  records are validated separately. The early execution boundary should treat
  user measurement code as the inside of the existing lab stack, with Scopecat
  owning declared intent, context, records, outcomes, and review outside that
  function boundary.

Routes may guide journey selection and cross-journey review. They do not own
contracts, implementation boundaries, API schemas, storage models, hardware
safety assumptions, or `JC` acceptance.

Move a route toward product acceptance only after accepted journeys or user
validation show that the route itself is a durable product direction.
