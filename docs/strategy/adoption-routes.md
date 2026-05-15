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
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Explain copied notebooks, scripts, runnable configuration, known-good sources, drift, and dry-run readiness before deployment or managed execution. |
| Experiment intent and readiness | `JC-007`, `JC-008`, `JC-016` | Preview, diff, freeze, and mock-check plan or queue intent before one bounded runtime handoff is considered. |
| Calibration and parameter review | `JC-003`, `JC-011`, `JC-012`, `JC-016` | Review calibration, parameter, declared-context, and advisory evidence before mutation or bounded apply. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. |
| Analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Trace figures, fits, reports, and claims back to source runs, processing choices, corrections, exclusions, and ambiguity. |

## Promotion Rule

Do not promote runtime ownership, managed execution, or a capability name into a
standalone adoption route until a lab can get useful value from adopting that
route alone.

Routes may guide journey selection and cross-journey review. They do not own
contracts, implementation boundaries, API schemas, storage models, hardware
safety assumptions, or `JC` acceptance.

Move a route toward product acceptance only after accepted journeys or user
validation show that the route itself is a durable product direction.
