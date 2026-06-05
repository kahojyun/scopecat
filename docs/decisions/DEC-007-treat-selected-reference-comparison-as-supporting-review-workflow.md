# DEC-007: Treat Selected Reference Comparison As A Supporting Review Workflow

## Status

Decision type: product.

Decision status: accepted.

Date: not recorded.

## Context

Users compare current work against known-good or otherwise selected references
to reproduce, rerun, prepare context, investigate differences, and review
completed results. The comparison behavior is useful across several journeys,
but comparison alone is not yet a proven standalone product journey.

## Decision

Treat selected reference comparison as a supporting review workflow. It may
support preparation, post-run review, calibration continuation, reproduction,
and handoff context, but it should become a standalone journey only if users
treat comparison itself as an independent job with a stable trigger, result,
product surface, and acceptance criteria.

The workflow should surface objective comparison findings without claiming
setup truth, user/domain judgment, rollback correctness, execution readiness,
or mutation authority.

## Scope

This decision applies to:

- selected reference comparison;
- declared measurement and context comparison;
- selected code-context comparison;
- reference-based reproduction and rerun preparation.

This decision does not apply to:

- final setup truth or scientific judgment;
- automatic rollback or repair;
- execution, deployment, hardware, or environment mutation;
- a future standalone selected-reference product journey after acceptance
  criteria are proven.

## Consequences

Selected reference work can remain reusable across journeys without forcing a
standalone UX or overclaiming what comparison findings mean. Consumers must
decide how they use findings instead of inheriting hidden authority from the
comparison workflow.

## Alternatives Considered

- Option: keep selected reference comparison as a target journey now. Rejected
  because the current evidence supports reusable review behavior, not yet an
  end-to-end user job.
- Option: fold comparison into each consuming journey. Rejected because the
  comparison vocabulary and evidence posture are shared across multiple
  workflows.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- users treat selected-reference comparison itself as an independent job;
- a route needs stable comparison results, product surface, and acceptance
  criteria;
- comparison findings are used to drive mutation, rollback, execution, or
  setup-truth claims.

## Related Evidence

- [`../product/target-journeys.md`](../product/target-journeys.md)
- [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md)
- [`../discovery/problem-briefs/selected-reference-comparison.md`](../discovery/problem-briefs/selected-reference-comparison.md)
