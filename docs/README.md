# Scopecat Documentation Map

Status: current documentation entry point
Date: 2026-06-29

Start with the current workflow documents. Keep new design notes only when
they define an active contract, a current sequencing rule, or a boundary that
would be hard to recover from code.

## Current Baseline

- [Project charter](project-charter.md): project scope, users, and direction.
- [Architecture](architecture.md): accepted package and boundary model.
- [Experiment workflow](experiment-workflow.md): public
  `Workspace -> Experiment -> Run -> Data -> Analysis` workflow.
- [Parameter system](parameter-system.md): accepted parameter-state and
  candidate-review model.
- [Native experiment kernel detail](native-experiment-definition-design.md):
  durable experiment kernel and adapter boundary.
- [GUI workbench entry contract](gui-workbench-entry-contract.md): future GUI
  navigation mapped onto the notebook-first objects.
- [Next development plan](next-development-plan.md): current sequencing rules
  and explicit deferrals.

## Storage And Data Contracts

- [Storage workspace and manifest contract](storage-workspace-manifest-contract.md)
- [Measurement storage backends contract](measurement-storage-backends-contract.md)
- [Diagnostics catalog](diagnostics-catalog.md)
- [PlanSnapshot preview storage contract](plan-snapshot-preview-storage-contract.md)
- [Relation execution and function registry contract](relation-execution-function-registry-contract.md)
- [Calibration state shape contract](calibration-state-shape-contract.md)
- [Diagnostics catalog contract](diagnostics-catalog-contract.md)

These documents describe durable records and internal boundaries. They may
mention older internal record-family names when those names describe existing
persistence internals, not the public UX model.

## Examples And Domain Boundaries

- [Domain package extraction contract](domain-package-extraction-contract.md):
  examples layout, demo support-package boundary, and criteria for extracting
  future domain packages.

## Pruned Documents

Completed migration notes and broad research backlogs should not stay as
separate files after their decisions are represented in current contracts. The
former workflow migration record, examples reorganization record, measurement
data-shapes backlog, and completed immediate engineering execution plan were
folded into the current workflow, development plan, domain-package,
measurement-storage, diagnostics, and example documents.
