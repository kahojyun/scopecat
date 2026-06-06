# Target Capability Map

## Status

Current target product capability map with candidate feature areas separated
from accepted product capabilities.

## Purpose

Track Scopecat product capabilities and their maturity. A capability may
support multiple journeys and may be implemented by one or more modules.

Use stable `CAP-*` IDs when referencing product capabilities from journey,
use-case, validation, implementation, decision, or risk documents.

This file owns capability maturity and advancement questions. Use
[`target-journeys.md`](target-journeys.md) for canonical journey/use-case to
capability relationships.

## Product Capabilities

| ID | Capability | Maturity | Evidence State | Open Advancement Questions |
| --- | --- | --- | --- | --- |
| CAP-001 | Measurement Records | Engineering prototype | Live prototype evidence | Decide whether production readiness for selected stored measurement export, existing-record update/import beyond ADR-0017, running measurement lifecycle, or storage schema publication beyond ADR-0017 is the next validation focus. |
| CAP-002 | Handoff Packages | Engineering prototype | Live prototype evidence | Decide whether to validate production readiness hardening, archive-backed import beyond ADR-0015 and ADR-0016, or a future persisted GUI/batch/context contract next. |
| CAP-003 | Parameter State Review | Discovery | Brownfield pain-point evidence | Restart from a named brownfield entrypoint before promoting implementation; decide whether reviewed parameter snapshots, compatibility-file writing, hardware apply, catalog discovery, automatic run start, or a shared parameter/run-context schema is justified by a workflow. |
| CAP-004 | Environment Operation | Discovery | Brownfield pain-point and historical evidence | Restart from a named brownfield entrypoint before promoting implementation; decide whether bounded manager operations, runtime-readiness review, manifest integration, manager expansion, execution hardening, or GUI/runtime monitoring is justified by a workflow. |
| CAP-005 | Experiment Code Context | Discovery | Brownfield pain-point and implementation-candidate evidence | Decide which concrete user step merits promotion first: record, materialize, observe editable folder, prepare rerun, or GUI review. |
| CAP-006 | Running Measurement Monitor | Discovery | Brownfield pain-point validation question | Validate whether Python measurement scripts can emit lifecycle/progress/partial-data events that a long-lived local GUI can monitor across multiple active measurements. |

## Candidate Feature Areas

Candidate feature areas are not product capabilities yet. Keep them here only
when discovery evidence suggests a reusable product area may emerge, but the
validated scope is still scenario-shaped.

| ID | Feature Area | Current Level | Evidence State | Promotion Question |
| --- | --- | --- | --- | --- |
| CAND-001 | Calibration Continuation Review | Scenario | Discovery and implementation-candidate evidence | Promote to a product capability only if repeated use cases require stable review state, continuation actions, and support expectations beyond one calibration scenario. |

## Update Rule

Update this map when a branch changes product capability maturity, product
boundary, evidence state, advancement questions, or promotes a candidate
feature area into a product capability.

Do not use this file to list every implementation entrypoint, brownfield
artifact family, legacy system component, test, or fixture.
