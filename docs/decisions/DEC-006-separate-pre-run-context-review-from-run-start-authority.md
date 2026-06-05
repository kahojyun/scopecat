# DEC-006: Separate Pre-Run Context Review From Run-Start Authority

## Status

Decision status: accepted.

Date: not recorded.

## Context

Prepared-run workflows need to assemble selected parameter, code, environment,
setup, and prior-context evidence before a manual run. In the brownfield
setting, existing systems and operators still own hardware apply and run start.
If Scopecat review surfaces imply approval or permission to run, the product
would take authority it has not earned.

## Decision

Keep pre-run context review separate from run-start authority. Scopecat may
compose review-ready summaries and record operator acknowledgement, deferral,
or notes, but it does not start runs, grant permission to run, apply hardware
state, or prove execution readiness by default.

## Scope

This decision applies to:

- JNY-002 Prepare A Manual Run;
- prepared-run context evidence and review receipts;
- parameter, code, environment, setup, and prior-context summaries used before
  a manual run;
- user-facing wording for acknowledgement, deferral, and notes.

This decision does not apply to:

- a future accepted workflow that explicitly earns run-start authority;
- hardware apply, scheduler, runner, or service lifecycle ownership;
- scientific validity or operator safety judgment.

## Consequences

Scopecat can help users inspect missing or risky context without becoming an
approval gate or run-control system. Later Measurement Records may reference a
prepared-run receipt as context evidence, but that receipt is not permission or
proof that the run should start.

## Alternatives Considered

- Option: model prepared-run review as approval. Rejected because it would
  overstate Scopecat's authority and create pressure toward hardware-control
  and run-start ownership.
- Option: avoid pre-run context review until execution ownership exists.
  Rejected because users still benefit from explicit context review while
  existing systems keep run-start authority.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- users need Scopecat to start a specific class of run;
- run-start authority, execution readiness, scheduling, or hardware safety
  review becomes an accepted product target;
- prepared-run acknowledgements are repeatedly misunderstood as approval.

## Related Evidence

- [`../product/target-journeys.md`](../product/target-journeys.md)
- [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md)
- [`../brownfield/migration-strategy.md`](../brownfield/migration-strategy.md)
