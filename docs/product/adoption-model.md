# Adoption Model

## Status

Current product adoption model.

## Purpose

Describe how users can adopt Scopecat around existing lab systems. This is a
product strategy document, not a workflow validation map, implementation
register, or migration project plan.

Use this document to separate:

- adoption path: how a user starts using Scopecat;
- brownfield boundary: what existing system behavior remains outside Scopecat;
- workflow: what user job the adoption path supports;
- capability: what Scopecat product ability must mature to support the path.

## Adoption Principles

- Start with useful review, selection, handoff, and diagnostic value before
  asking users to replace working measurement systems.
- Prefer explicit Python or adapter-authored recording over passive scraping as
  the first integration model.
- Keep existing systems responsible for low-level hardware control until a
  narrower workflow proves replacement is worth the risk.
- Make cross-machine value concrete through open-before-import packages,
  preview, and explicit import decisions.
- Treat selective migration as optional and capability-specific, not as a
  project-wide rewrite.

## Adoption Paths

| Adoption Path | User Change | Brownfield Boundary | Supporting Capabilities | Current Maturity |
| --- | --- | --- | --- | --- |
| Post-run record-first | User keeps running measurements in the existing system, then records declared run facts, source references, optional converted primary data, and review evidence in Scopecat. | Existing system still owns execution, raw historical file semantics, and scientific validity. Scopecat owns declared facts and local storage visibility. | Measurement Records, Parameter State Review, Experiment Code Context later. | Engineering prototype through Measurement Records storage visibility; broader sidecar review remains discovery evidence. |
| Portable handoff-first | User selects useful measurement data and sends a Scopecat-authored package for read-only review, preview, and later import on another computer. | Scopecat owns the package/export boundary it writes; existing lab storage and user-managed context may remain references unless explicitly packaged. | Handoff Packages, Measurement Records. | Engineering prototype at both ends; selected stored Measurement Record to single-measurement package export remains the main composition gap. |
| Review-before-import | Receiving user opens a package or candidate record for orientation before accepting storage mutation. | Read-only package use and review are separate from import/organization authority. | Handoff Packages, Measurement Records. | Engineering prototype for package open/preview/gate/import plan and durable import adapter. |
| Parameter review before apply | User reviews adapter or calibration parameter-state facts before a run without Scopecat applying hardware changes. | Existing systems still own live write-back and hardware apply unless a later workflow earns that authority. | Parameter State Review, Measurement Records context links later. | Engineering prototype for review, storage, read view, selection, and route-local pre-run consumption. |
| Explicit experiment-code recording | User records the code context that mattered for a run or step without adopting Git-facing workflow up front. | User-managed code and environments remain authoritative until a later materialization, restore, or execution workflow is validated. | Experiment Code Context, Environment Operation. | Discovery/implementation-candidate evidence; no live product capability owner yet. |
| Running monitor | User keeps a local GUI open while Python-driven measurements emit lifecycle, progress, partial data, and completion events. | Python measurement code still owns experiment execution; Scopecat observes and records lifecycle/review state without controlling hardware or scheduling. | Running Measurement Monitor, Measurement Records, optional app runtime. | Discovery/validation question. |
| Selective legacy replacement | A lab replaces one fragile legacy service, driver, scan boundary, or helper workflow only when that replacement reduces operational risk. | Replacement is local and capability-specific. It does not imply Scopecat becomes a universal hardware-control framework. | Depends on the selected workflow and backend. | Future explicit decision. |

## Update Rule

Update this model when a branch changes how users are expected to start using
Scopecat, changes brownfield boundaries, or validates a new adoption path.

Do not use this file to track implementation entrypoints, tests, fixtures, or
module ownership. Use [`../engineering/implementation-register.md`](../engineering/implementation-register.md)
for live implementation ownership and [`capability-map.md`](capability-map.md)
for product capability maturity.
