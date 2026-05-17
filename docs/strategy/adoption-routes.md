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

| Route hypothesis | Related `JC` refs | First useful output | Behavior change being tested | Promotion threshold |
| --- | --- | --- | --- | --- |
| Run selection and analysis handoff | `JC-001`, `JC-002`, `JC-006`, `JC-015` | Selected-run preview plus portable pre-analysis package with source identity and missing-context warnings. | Users mark useful runs and move/open the package on an analysis computer instead of manually copying folders and reconstructing context. | Handoff is valuable when the package is easier than the current copy-and-reopen workflow; `JC-001` supplies minimum bundle identity, not a requirement to finish full provenance before handoff. |
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Entrypoint plus selected-folder snapshot/checkpoint, compare view, and readiness notes. | Users choose, restore, or migrate the next code version through explicit checkpoints instead of copying folders and guessing which version is working. | Promote only if selection or recovery helps next-run work; retrospective provenance alone is insufficient. |
| Experiment intent and readiness | `JC-007`, `JC-008` | Fixture-scale declared intent plus recorded or simulated outcome report, with review gates and requested next action. | Users or helper APIs express grouped calibration intent and review outcomes instead of encoding all continuation logic in notebook cells. | Keep as validation pressure until builder/decorator authoring and outcome reports beat handwritten sequencing; execution support needs observed transcript evidence and a runtime boundary. |
| Calibration and parameter memory | `JC-003`, `JC-011`, `JC-012` | Parameter history/query view with working-point branches, direct-update checkpoints, bad-state labels, and run links. | Users keep direct update style but commit/query parameter states instead of overwriting mutable files and remembering bad writes manually. | Promote before mutation ownership only if retry, drift query, and working-point recovery are useful without Scopecat-owned apply. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Known-good comparison or gap report that shows changed evidence without claiming equivalence. | Users compare a current bundle, machine, setup, sample, or method variant against a selected reference before deciding what to trust or repair. | Promote only as diagnostic value; rollback, deployment, equivalence scoring, and setup truth authority need later decisions. |
| Downstream analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Figure, fit, report, or claim impact view linked to source runs, processing choices, corrections, exclusions, and ambiguity. | Users recheck derived analysis after a handoff, calibration, setup, code, or analysis change instead of tracing notebooks and files manually. | Keep downstream until concrete analysis or review work creates demand; do not use it as the first adoption story by itself. |

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
