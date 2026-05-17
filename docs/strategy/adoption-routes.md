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

Route value should be phrased around the workflow return that would make a lab
change behavior: convenience, recovery, selection, packaging, readable progress,
or bounded automation. Provenance, auditability, and lineage matter, but they
should usually appear as benefits of the structured workflow unless a route is
explicitly downstream analysis or review work.

The canonical `JC` candidate wording, evidence basis, and boundaries still live
in [`../evidence/inventory.md`](../evidence/inventory.md). The tracker owns
phase and coordination only.

## Route Hypotheses

| Route hypothesis | Related `JC` refs | Standalone value being tested |
| --- | --- | --- |
| Run selection and analysis handoff | `JC-001`, `JC-002`, `JC-006`, `JC-015` | Find, preview, reopen, select, package, export/import, optionally discover through shared storage, and later trace measurement work without replacing acquisition code or requiring remote connection. |
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Choose usable entrypoints, snapshots, known-good sources, one-time migrations, and readiness checks around copied notebooks and scripts before any deployment, code-version loader, automatic sync, or managed-runner capability is accepted. |
| Experiment intent and readiness | `JC-007`, `JC-008` | Reduce hand-written sequencing and calibration-batch bookkeeping through reviewable intent, outcome reports, and readiness checks; strong adoption payoff likely requires continuation behavior such as resume, retry, review continuation, or selected remeasurement before managed execution or broader runtime ownership is considered. |
| Calibration and parameter memory | `JC-003`, `JC-011`, `JC-012` | Make retry, working-point selection, drift queries, direct-update checkpoints, bad-state labeling/exclusion, and measurement-time fit/readiness easier before separating proposal/review, apply, or mutation-ownership decisions. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. |
| Downstream analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Recheck figures, fits, reports, and claims by tracing them back to source runs, processing choices, corrections, exclusions, and ambiguity after handoff or analysis work has created a concrete need. |

`JC` overlap means shared evidence or composition pressure, not route
ownership. A route may reference the same `JC` as another route only to show
that a validated slice could support multiple adoption stories. `JC-016` is
intentionally excluded from route membership because it is a quarantined
runtime-boundary hypothesis, not a route.

## Cross-Route Constraints

Same-station data access is not a standalone route yet. Preserve it as a
validation constraint on run explanation, analysis handoff, and durable reopen:
stable opaque `record_id`, legacy source refs, machine-specific locations,
optional shared-storage refs, and read capabilities should let another
same-station computer resolve historical records without treating the
control-PC path as identity.

The candidate validation ladder is local durable record -> export/import
selected runs or sample/cooldown packages -> optional NAS/shared-folder
references or discovery probes. Shared storage is a possible transport and
discovery backend, not mandatory architecture. Generated indexes, local index
caches, a deployed database, background indexer service, or live sync service
require later route evidence and an ADR. A remote execution service is not a
record-access route; it requires accepted journey evidence and a
runtime/resource ownership decision.

Historical browsing from another computer may be solved by portable handoff
packages, so it should not be used by itself to justify remote connection.
Live observation and remote execution remain later scope.

This constraint makes Scopecat distributed-record-aware, not a distributed
experiment-control system. Shared record discovery must not imply shared
instrument authority. If several computers or users can reach the same
instruments, conflicts remain handled by lab convention, physical or network
isolation, existing control systems, booking, or direct coordination until
accepted journey evidence and a runtime/resource ownership decision validate
leases, permissions, arbitration, and failure behavior.

Cross-computer code movement should also stay explicit at first. One-time
folder migration is a weak pain; ongoing edits across computers are the
stronger source-of-truth problem. Validate the smallest useful vocabulary
first, such as selected folder, entrypoint, snapshot/checkpoint, compare,
restore or select previous version, and machine-local config separation. Treat
publish, pull/update, automatic sync, Git hosting, deployment management, and
load-selected-version execution as later capability hypotheses until smaller
prototypes show they are needed.

## Promotion Rule

Keep runtime ownership, managed execution, code registry, automatic version
management, proposal workflow, and similar solution-shaped names out of
adoption routes by default. Treat them as capability hypotheses; promote only
pain-framed routes after accepted journey evidence or user validation shows
standalone workflow value, and after any required ADR or safety decision.

Use the owning evidence and fixture docs for lower-level evidence and fixture
questions:
[`../evidence/inventory.md`](../evidence/inventory.md) owns `JC` candidate
wording and boundaries, while
[`../evidence/pain-discovery-fixtures.md`](../evidence/pain-discovery-fixtures.md)
owns current fixture questions and support levels. Fixture notes should not
define route promotion by themselves.

Routes may guide journey selection and cross-journey review. They do not own
contracts, implementation boundaries, API schemas, storage models, hardware
safety assumptions, or `JC` acceptance.

Move a route toward product acceptance only after accepted journeys or user
validation show that the route itself is a durable product direction and that
the user-facing workflow return justifies adopting the route, including any
required rewrite of route-owned experiment code.
