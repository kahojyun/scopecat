# Capability Register

## Status

Product capability maturity register.

## Purpose

This register records Scopecat product capabilities, their current maturity,
and their implementation owners. It complements
[`workflow-validation-map.md`](workflow-validation-map.md):

- the workflow map answers what user workflow has been validated and which
  seams remain missing;
- this register answers which capability is maturing, what workflows it
  supports, what evidence backs that maturity, and where implementation details
  live.

Use this document before adding live code or before treating a discovery
candidate, prototype, or fixture result as product progress.

## How To Read

- Each row is a product capability, not a final architecture component or
  separate tool.
- `Maturity` is the current delivery maturity for that capability. A capability
  may support workflows that are less mature than the capability's core
  behavior.
- `Supported Workflows` links capability progress back to user work, not to
  candidate count.
- `Evidence` summarizes the validation or implementation evidence without
  copying validation-result tables.
- `Implementation Owner` points to the module README and prototype-boundary
  note that own details.
- `Open Advancement Questions` names what must be answered before the
  capability can move toward a production vertical slice, production readiness,
  or maintained product capability.

## Capability Register

| Capability | Maturity | Supported Workflows | Current Product Boundary | Evidence | Implementation Owner | Open Advancement Questions |
| --- | --- | --- | --- | --- | --- | --- |
| Measurement Records | Engineering prototype | Normalized primary data becomes a durable Measurement Record; legacy external run becomes visible in local storage; stored records support later review and handoff workflows. | Route-local storage APIs create, finalize, read, refresh, and review Measurement Records under a caller-provided storage root. Legacy run storage records declared external-run facts and optional converted primary data without requiring immediate legacy-system replacement. | Measurement Records unit tests, legacy storage scenario fixtures, measurement fixture families, and prototype boundary notes. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`prototype-boundaries/measurement-records-creation-lifecycle.md`](prototype-boundaries/measurement-records-creation-lifecycle.md), [`prototype-boundaries/measurement-records-legacy-run-storage.md`](prototype-boundaries/measurement-records-legacy-run-storage.md) | Decide whether selected stored measurement export, existing-record update/import, running measurement lifecycle, or storage schema readiness is the next vertical-slice pressure. |
| Handoff Packages | Engineering prototype | Source-root data becomes a local handoff package; handoff package is opened, previewed, gated, planned, and imported into another storage root. | Directory-shaped handoff packages can be written, reopened, inspected locally, integrity-observed, receiving-gated, import-planned, and imported through the Measurement Records durable import adapter. | Handoff fixture families, prototype fixtures, module tests, handoff package boundary notes, and durable import boundary note. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`prototype-boundaries/handoff.md`](prototype-boundaries/handoff.md), [`prototype-boundaries/handoff-durable-import-storage.md`](prototype-boundaries/handoff-durable-import-storage.md) | Validate selected stored Measurement Record to single-measurement handoff package export; decide later trust/authenticity, batch receiving, archive format, and linked-context payload import questions. |
| Environment Operation | Engineering prototype | Approved environment-manager intent becomes local operation evidence for review before run preparation or operator review consumes it. | Approved `uv sync` intent can execute through a bounded route-local operation path, produce typed result/review objects, and optionally run a bounded interpreter fact probe. | Environment-operation unit tests, environment fixture families, prototype fixtures, and environment-operation boundary note. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md), [`prototype-boundaries/environment-operation.md`](prototype-boundaries/environment-operation.md) | Decide whether runtime readiness, manifest integration, manager expansion, execution hardening, or GUI/runtime monitoring is the next validated product need. |
| Parameter State Review | Engineering prototype | Parameter state is reviewed, stored, read, selected, and consumed for manual pre-run review. | Adapter-authored previews, reviewed parameter-state storage, manifest/receipt read views, source-agnostic projections, selection context, and pre-run review-chain consumption are route-local prototype behavior. | Parameter-state unit tests, parameter fixture families, and parameter-state boundary note. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md), [`prototype-boundaries/parameter-state.md`](prototype-boundaries/parameter-state.md) | Decide whether compatibility-file writing, hardware apply, catalog discovery, automatic run start, or a shared parameter/run-context schema is justified by a workflow. |
| Running Measurement Monitor | Discovery / validation question | User keeps a local GUI open while multiple Python-driven measurements run, showing lifecycle, progress, partial data, stale/failure state, and completion into durable records. | No accepted live owner yet. This is a candidate future app-runtime capability, not a commitment to a remote backend, scheduler, workflow engine, or hardware-control layer. | User workflow pressure and adjacent Measurement Records storage/review evidence; no production-shaped live-monitor prototype yet. | No live module owner. Future work should decide whether this belongs in a GUI/app-runtime module, Measurement Records lifecycle extension, or both. | Validate whether Python measurement scripts can emit lightweight Scopecat lifecycle/progress/partial-data events that a long-lived local GUI can monitor across multiple active measurements without controlling the experiment. |

## Update Rule

Update this register when a branch:

- adds, retires, renames, or materially changes a product capability;
- changes a capability's maturity, workflows, implementation owner, evidence,
  or open advancement questions;
- promotes a workflow gap into an engineering prototype, production vertical
  slice, production-readiness review, or maintained product capability;
- shows that a validation artifact should remain evidence rather than product
  progress.

Do not copy validation-result tables here. Link to the owner and summarize only
the product maturity claim and current implementation boundary.
