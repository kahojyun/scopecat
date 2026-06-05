# Engineering Archive

## Status

Compact historical index.

## Purpose

Index engineering prototype plans, readiness checkpoints, and retired candidate
decisions whose detailed bodies were removed from the active documentation
tree. Git history preserves the full notes.

Use [`../prototype-boundaries/`](../prototype-boundaries/) for current
prototype boundaries and [`../implementation-register.md`](../implementation-register.md)
for active implementation ownership.

## Former Notes

| Former Note | Historical Coverage | Current Owner |
| --- | --- | --- |
| `environment-operation-prototype-plan.md` | Environment-operation prototype objective, scope, non-claims, and stop conditions. | Workflow validation map and product capability map until a named brownfield entrypoint reopens the capability. |
| `environment-operation-prototype-readiness.md` | Readiness checkpoint that ended the broad environment-operation prototype line. | Workflow validation map and product capability map. |
| `handoff-prototype-plan.md` | Handoff prototype objective, scope, fixture policy, stop conditions, and promotion criteria. | Handoff module README, handoff prototype-boundary note, and DEC-010 through DEC-025. |
| `handoff-prototype-readiness.md` | Readiness checkpoint that ended the broad handoff prototype line. | Handoff module README and handoff prototype-boundary note. |
| `handoff-candidate-storage-acceptance.md` | Retired first candidate storage acceptance mutation and rollback decision. | Handoff durable-import boundary, Measurement Records boundary, and DEC-025. |
| `handoff-storage-import-requirements-synthesis.md` | Pre-durable-import storage/import requirements synthesis. | Handoff durable-import boundary and Measurement Records module README. |
| `parameter-state-prototype-retirement.md` | Retired parameter-state prototype, overfit fixture shape, and retained domain concepts. | Domain model, context map, and future entrypoint-specific design if parameter state is reopened. |

## Deleted Body Policy

Do not restore archived engineering bodies wholesale. If future work needs one
fact from a removed note, recover the narrow fact from Git history and move it
into the current owner.
