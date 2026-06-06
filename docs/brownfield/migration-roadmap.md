# Brownfield Migration Roadmap

## Status

Current design-validation sequence for brownfield migration.

## Purpose

Sequence brownfield migration by named use cases and authority boundaries.

This is not an implementation task list and not an adoption-order mandate. A
lab may start where pain is strongest; the roadmap preserves dependency order
for cleaner product boundaries.

## Sequencing Principles

- Advance by named use cases, not by shared domain model extraction.
- Prefer review, package, record, and bridge value before execution or hardware
  authority.
- Keep legacy-specific parsing and target product concepts separate.
- Promote shared domain concepts only after repeated slices need the same
  stable contract.
- Keep reusable context and comparison work as supporting workflows until a
  consuming journey proves an independent user goal.
- Link new review outputs back to a Measurement Record or another named
  Scopecat boundary only when the use case needs continuity.

## Design Validation Sequence

| Order | Target Boundary | Related Use Cases | Validation Focus | Decision Gate | Related Risks | Related ADRs |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | JNY-007 Record Runs / CAP-001 Measurement Records | UC-001, UC-002 | Decide which first user-facing route should own recording beyond the current Measurement Records capability path. | The route has explicit source posture, reviewed primary-data handling, repository-safe context references, and clear non-claims around legacy execution, adapter discovery, and scientific validity. | BR-RISK-003, BR-RISK-004, BR-RISK-011 | ADR-0003, ADR-0017 |
| 2 | JNY-001 Share A Selected Measurement | UC-006, JNY-001-SMOKE | Decide whether selected-record handoff needs production-readiness hardening, batch export productization, linked-context payload follow-up, or a different product fork. | Handoff remains centered on sharing a selected Measurement Record, not absorbing record creation, running updates, or post-run results review. | BR-RISK-003, BR-RISK-004, BR-RISK-010 | ADR-0002, ADR-0003, ADR-0006, ADR-0007, ADR-0015, ADR-0016, ADR-0017 |
| 3 | JNY-002 Prepare A Manual Run | UC-CAND-002 | Decide whether prepared-run context review becomes a live route owner or remains discovery evidence. | The use case has explicit input, review, acknowledgement or deferral, no-run-start semantics, and a receipt shape that a later Measurement Record can reference. | BR-RISK-001, BR-RISK-007, BR-RISK-008, BR-RISK-009 | ADR-0004 |
| 4 | Parameter/setup supporting work | Setup binding supporting workflow; future candidate from CAP-003 pressure | Decide which parameter/setup maintenance work is needed first by prepared-run review: history, comparison, plotting, setup-binding snapshot, adapter summary, or accepted-write review. | Parameter/setup work stays a capability or supporting workflow unless a repeated independent user job emerges; it must not imply hardware apply, live-instrument state ownership, universal setup truth, or broad runtime data-policy ownership. | BR-RISK-005, BR-RISK-007, BR-RISK-008, BR-RISK-009 | ADR-0001, ADR-0004, ADR-0005 |
| 5 | JNY-008 Browse And Review Completed Results | UC-CAND-007 | Choose the first live post-run route: records browser, plotter, readiness-review receipt, or a narrow composition of those surfaces. | Users can find, inspect, plot, and assess completed or near-completed results before handoff, comparison, calibration continuation, or rerun preparation without replacing canonical source evidence. | BR-RISK-003, BR-RISK-006, BR-RISK-007, BR-RISK-010 | ADR-0017 |
| 6 | JNY-004 Monitor A Running Measurement | UC-CAND-004 | Prove lifecycle/progress/partial-data event recording from Python-driven measurements. | Monitoring provides review value without becoming scan control, scheduling, automatic retune, or execution ownership. | BR-RISK-001, BR-RISK-007 | ADR-0004 |
| 7 | JNY-003 Recover Or Continue Calibration Work | UC-CAND-005 | Decide whether calibration continuation is a repeated product capability or remains brownfield pressure. | Repeated use cases require stable calibration review state, continuation action recording, and support expectations beyond one scenario. | BR-RISK-001, BR-RISK-005, BR-RISK-007 | ADR-0001 |
| 8 | JNY-009 Reproduce Or Rerun From A Reference | UC-CAND-003, UC-CAND-006 | Choose whether the first concrete step is reference selection, declared context comparison, selected-code comparison, workspace materialization, or rerun preparation. | The selected reproduction/rerun use case has a user goal independent of generic Git replacement, package management, or experiment execution ownership. | BR-RISK-005, BR-RISK-007, BR-RISK-009 | ADR-0001, ADR-0005 |

## Deferred Cross-Cutting Work

Defer until multiple validated use cases need the same contract:

- shared measurement/context domain model extraction;
- generalized artifact parser framework;
- universal setup, sample, topology, or parameter ontology;
- broad runtime readiness framework;
- hardware apply and live write-back authority;
- general driver, scan, service, or scheduling ownership.

## Update Rule

Update this roadmap when the design-validation sequence, validation focus, or
decision gates change.

Do not use this file to list active tasks, owners, deadlines, test names,
fixtures, implementation modules, detailed validation evidence, or canonical
journey/use-case membership.
