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
| Same-station data access | `JC-011`, `JC-015`, `JC-017` | Let another same-LAN station computer browse historical records and optionally observe running-run data without taking over hardware control or requiring cross-setup migration. |
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Explain copied notebooks, scripts, static entrypoint evidence, user-code snapshots, known-good sources, drift, and readiness before any deployment, code-version loader, or managed-runner capability is accepted. |
| Experiment intent and readiness | `JC-007`, `JC-008`, `JC-016` | Evidence-backed value starts with reviewable intent and outcome reports; minimal local execution, shared-resource hints, review gates, and requested resume/remeasure actions remain fixture-gated hypotheses before managed execution or broader runtime ownership is considered. |
| Calibration and parameter memory | `JC-003`, `JC-011`, `JC-012`, `JC-016` | Start with parameter drift queries, branch or working-point history, run linkage, direct-update history, bad-state labeling/exclusion, declared-context, and running-run read/monitor evidence before separating prior-version retry, proposal/review, apply, or mutation-ownership decisions. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. |
| Analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Trace figures, fits, reports, and claims back to source runs, processing choices, corrections, exclusions, and ambiguity. |

## Promotion Rule

Keep runtime ownership, managed execution, code registry, automatic version
management, proposal workflow, and similar solution-shaped names out of
adoption routes by default. Treat them as capability hypotheses; promote only
pain-framed routes after accepted journey evidence or user validation shows
standalone value, and after any required ADR or safety decision.

Current corrective stance:

- `JC-008` should validate helper-authored batch intent, simulated or
  lab-owned outcome reports, and then a separate observed minimal-executor
  transcript for bounded grouped calibration if that remains necessary. It is
  not a managed runner.
- `JC-003` should start from parameter memory, drift, branches or working
  points, run linkage, direct-update history, and bad-state handling. Bad
  states should be kept by default with yank/exclusion-style semantics; hard
  delete is a cleanup path, not the default history model. Explicit
  proposal/review is optional future scope.
- `JC-016` remains a capability hypothesis until lower-level local execution,
  explicit recording, parameter memory, stop behavior, runtime owner, and audit
  records are validated separately. The early execution boundary should treat
  user measurement code as the inside of the existing lab stack, with Scopecat
  owning declared intent, context, records, outcomes, and review outside that
  function boundary.
- `JC-017` should validate read-only same-station browsing before remote
  experiment execution. Shared folders are a baseline for simple file-based
  systems, but they should not define the richer realtime read/monitor path.

Routes may guide journey selection and cross-journey review. They do not own
contracts, implementation boundaries, API schemas, storage models, hardware
safety assumptions, or `JC` acceptance.

Move a route toward product acceptance only after accepted journeys or user
validation show that the route itself is a durable product direction.
