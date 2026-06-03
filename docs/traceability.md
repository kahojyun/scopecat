# Traceability Map

## Status

Current lightweight traceability map.

## Purpose

Connect brownfield current-state pressure to target journeys, use cases,
capabilities, validation state, and implementation owners. This is a navigation
map, not a roadmap, task list, decision record, or complete requirements
matrix.

Use this map when checking whether a discovery result, product journey,
capability, validation row, or implementation owner is drifting away from the
same user problem.

## Reading Rules

- Keep rows at journey/use-case scale, not fixture or function scale.
- Link to owners instead of duplicating their full content.
- Add a row only when multiple documents need the same trace.
- Leave unknown or unclassified pressure in the current-state or discovery
  owner until it has a target journey or validation question.

## Core Traces

| Current-State Pressure | Target Journey | Use Case Or Seam | Capabilities | Validation Owner | Implementation Owner |
| --- | --- | --- | --- | --- | --- |
| Selected measurements are reconstructed from folders, notebooks, reports, sidecars, and memory before handoff. | JNY-001 | UC-CAND-001. | CAP-001, CAP-002. | [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md) | `scopecat.measurement_records`, `scopecat.handoff` in [`engineering/implementation-register.md`](engineering/implementation-register.md) |
| Externally produced runs need low-intrusion recording without replacing the legacy runner. | JNY-001 | UC-001; UC-002. | CAP-001. | [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md), [`discovery/routes/measurement-records/legacy-brownfield-adoption-decision.md`](discovery/routes/measurement-records/legacy-brownfield-adoption-decision.md) | `scopecat.measurement_records` |
| Users need to inspect selected parameter, code, setup, and environment context before a manual run. | JNY-002 | UC-005; UC-CAND-002. | CAP-003, CAP-005, CAP-004, CAP-001 context links. | [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md) | `scopecat.parameter_state`, `scopecat.environment_operation` |
| Code context is reconstructed from copied folders, notebooks, helper libraries, backups, and editable working trees. | JNY-005 | UC-CAND-003. | CAP-005, CAP-004. | [`brownfield/migration-roadmap.md`](brownfield/migration-roadmap.md), discovery experiment-code route. | No live product capability owner yet; related operation evidence in `scopecat.environment_operation`. |
| Long-running measurements expose partial data and progress before full completion. | JNY-004 | UC-CAND-004. | CAP-006, CAP-001. | [`brownfield/migration-roadmap.md`](brownfield/migration-roadmap.md), [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md) | No live monitor owner yet; related Measurement Records inspection pressure. |
| Calibration continuation depends on notebook state, fit previews, manual decisions, proposed writes, and downstream blocking. | JNY-003 | UC-CAND-005. | CAND-001, CAP-003, CAP-001 context links. | [`discovery/routes/calibration-continuation/decision.md`](discovery/routes/calibration-continuation/decision.md), [`brownfield/migration-roadmap.md`](brownfield/migration-roadmap.md) | No live calibration route owner yet; parameter-state bridge evidence exists. |
| Users compare current work against last-working or notable references by reopening files, notebooks, setup notes, and memory. | JNY-006 | UC-CAND-006. | CAP-001, CAP-005, CAP-003. | [`product/target-journeys.md`](product/target-journeys.md), selected-reference discovery route. | No live selected-reference owner yet. |
| Users need to move package contents between computers but inspect before import or organization. | JNY-001 | UC-004. | CAP-002, CAP-001. | [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md) | `scopecat.handoff`, `scopecat.measurement_records` |

## Cross-Cutting Trace Rules

- Current-state pressure is sampled evidence, not an exhaustive source of
  truth.
- Target journeys are current hypotheses and may split, merge, retire, or
  become supporting workflows.
- Capabilities may support multiple journeys; do not infer a shared domain
  model from one row.
- Validation rows prove named behavior only; they do not automatically promote
  candidate fixtures, summaries, or route-local vocabulary into product
  contracts.
- Implementation owners own live behavior, not the full product journey.

## Update Rule

Update this map when a branch changes a target journey, use-case seam,
capability owner, validation owner, or live implementation owner in a way that
would make an existing trace misleading.
