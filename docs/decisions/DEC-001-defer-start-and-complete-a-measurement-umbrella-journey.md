# DEC-001: Defer Start And Complete A Measurement As An Umbrella Journey

## Status

Decision status: accepted.

Date: not recorded.

## Context

The end-to-end lab lifecycle includes preparation, run start, execution,
monitoring, result recording, failure recovery, post-run review, sharing,
calibration continuation, and reproduction. Treating that entire lifecycle as
one current Scopecat journey would couple too many authority boundaries before
the narrower workflows have earned them.

## Decision

Defer `Start And Complete A Measurement` as an umbrella journey. Scopecat
should acknowledge the lifecycle, but current product direction must prove
smaller journeys around preparation, recording, monitoring, review, handoff,
calibration continuation, and reproduction before accepting the full umbrella.

## Scope

This decision applies to:

- target journey planning;
- brownfield migration sequencing;
- run-start, execution, monitoring, recording, review, recovery, and handoff
  boundary discussions.

This decision does not apply to:

- narrow journey validation for preparation, recording, monitoring, review,
  handoff, calibration continuation, or reproduction;
- future run-start or execution authority after a named workflow earns it.

## Consequences

Scopecat can make progress through smaller user-recognizable workflows without
implicitly taking hardware safety, scan execution, scheduling, recovery, or
whole-run orchestration responsibility.

The tradeoff is that the full lifecycle remains a composition target rather
than a single accepted journey until a narrower slice proves the required
authority boundaries together.

## Alternatives Considered

- Option: accept `Start And Complete A Measurement` as a current journey.
  Rejected because it would bundle run-start authority, code execution,
  environment readiness, monitoring, result recording, recovery, review, and
  handoff before narrower workflows have stable contracts.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- a named use case proves manual review, explicit run-start authority,
  execution boundary, monitoring, result recording, post-run review, and
  recovery expectations together;
- Scopecat intentionally moves toward run-start, scheduling, execution, or
  hardware-control ownership.

## Related Evidence

- [`../product/target-journeys.md`](../product/target-journeys.md)
- [`../brownfield/migration-roadmap.md`](../brownfield/migration-roadmap.md)
- [`../brownfield/migration-strategy.md`](../brownfield/migration-strategy.md)
