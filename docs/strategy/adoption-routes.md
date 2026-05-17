# Adoption Routes

## Status

Provisional route-definition owner.

This document names product-value route hypotheses so the progress tracker does
not become a hidden strategy document or backlog. These routes are not a
roadmap, capability map, subsystem map, implementation order, or product
acceptance claim.

## Purpose

Preserve route hypotheses only when they name standalone user value that could
be adopted progressively. Route value should be phrased around the workflow
return that would make a lab change behavior: convenience, recovery, selection,
packaging, readable progress, or bounded automation.

Provenance, auditability, and lineage matter, but they should usually appear as
benefits of the structured workflow unless a route is explicitly downstream
analysis or review work.

Evidence and pain rows live in [`../evidence/inventory.md`](../evidence/inventory.md).
The tracker owns phase and coordination only.

## Route Hypotheses

| Route hypothesis | Evidence pressure | First useful output | Behavior change being tested | Promotion threshold |
| --- | --- | --- | --- | --- |
| Run selection and analysis handoff | Existing bundle ambiguity, selected-context loss, source identity, portable record movement, and handoff pressure. | Selected-run preview plus portable pre-analysis package with source identity and missing-context warnings. | Users mark useful runs and move/open the package on an analysis computer instead of manually copying folders and reconstructing context. | Handoff is valuable when the package is easier than the current copy-and-reopen workflow; full provenance is not a prerequisite if the package exposes unresolved gaps. |
| Method and code portability diagnostics | Copied folders, notebooks, entrypoints, dependency readiness, known-good references, and cross-computer code drift. | Entrypoint plus selected-folder snapshot/checkpoint, compare view, and readiness notes. | Users choose, restore, or migrate the next code version through explicit checkpoints instead of copying folders and guessing which version is working. | Promote only if selection or recovery helps next-run work; retrospective provenance alone is insufficient. |
| Experiment intent and readiness | Scan semantics, grouped calibration intent, review gates, static readiness, failure policy, and outcome records. | Fixture-scale declared intent plus recorded or simulated outcome report, with review gates and requested next action. | Users or helper APIs express grouped calibration intent and review outcomes instead of encoding all continuation logic in notebook cells. | Keep as validation pressure until builder/decorator authoring and outcome reports beat handwritten sequencing; execution support needs observed transcript evidence and a runtime boundary. |
| Calibration and parameter memory | Mutable parameter files, direct updates, bad states, drift queries, working-point branches, and run links. | Parameter history/query view with working-point branches, direct-update checkpoints, bad-state labels, and run links. | Users keep direct update style but commit/query parameter states instead of overwriting mutable files and remembering bad writes manually. | Promote before mutation ownership only if retry, drift query, and working-point recovery are useful without Scopecat-owned apply. |
| Trust, diagnostics, and comparability | False confidence, setup reality, known-good references, scientific comparability, support packages, and control-PC safety. | Known-good comparison or gap report that shows changed evidence without claiming equivalence. | Users compare a current bundle, machine, setup, sample, or method variant against a selected reference before deciding what to trust or repair. | Promote only as diagnostic value; rollback, deployment, equivalence scoring, and setup truth authority need later decisions. |
| Downstream analysis and claim lineage | Derived arrays, figures, fits, reports, correction choices, exclusions, source runs, and calibration impact. | Figure, fit, report, or claim impact view linked to source runs, processing choices, corrections, exclusions, and ambiguity. | Users recheck derived analysis after a handoff, calibration, setup, code, or analysis change instead of tracing notebooks and files manually. | Keep downstream until concrete analysis or review work creates demand; do not use it as the first adoption story by itself. |

Route overlap means shared evidence or composition pressure, not route
ownership. A route can reuse the same evidence pressure as another route only
to show that a future validated slice could support multiple adoption stories.

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
record-access route; it requires accepted validation evidence and a
runtime/resource ownership decision.

Cross-computer code movement should stay explicit at first. One-time folder
migration is a weak pain; ongoing edits across computers are the stronger
source-of-truth problem. Validate the smallest useful vocabulary first:
selected folder, entrypoint, snapshot/checkpoint, compare, restore or select
previous version, and machine-local config separation. Treat publish,
pull/update, automatic sync, Git hosting, deployment management, and
load-selected-version execution as later capability hypotheses until smaller
validation work shows they are needed.

## Promotion Rule

Keep runtime ownership, managed execution, code registry, automatic version
management, proposal workflow, and similar solution-shaped names out of
adoption routes by default. Treat them as capability hypotheses. Promote only
pain-framed routes after user validation or thin validation work shows
standalone workflow value, and after any required ADR or safety decision.

Use the owning evidence and pain-packet docs for lower-level questions:
[`../evidence/inventory.md`](../evidence/inventory.md) owns evidence and pain
rows, while
[`../evidence/pain-packets/README.md`](../evidence/pain-packets/README.md)
owns current failure packets and support levels. Pain packets should not define
route promotion by themselves.

Routes may guide scenario or validation-charter selection and cross-option
review. They do not own contracts, implementation boundaries, API schemas,
storage models, hardware safety assumptions, or accepted product scope.
