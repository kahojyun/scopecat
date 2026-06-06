# Brownfield

## Status

Brownfield architecture and migration documentation.

## Purpose

Brownfield docs describe the existing lab-system reality Scopecat is designed
around, the pain points created by that reality, the transition architecture
between current workflows and target Scopecat journeys, and the migration
strategy for moving authority one boundary at a time.

These docs are internal product and architecture memory. They are not public
user documentation, implementation plans, or task queues.

## Documents

| Document | Use For |
| --- | --- |
| [`current-state-assessment.md`](current-state-assessment.md) | As-is lab workflow and artifact patterns observed from current-state evidence. |
| [`pain-points.md`](pain-points.md) | Brownfield workflow friction, user impact, current workarounds, Scopecat opportunities, related owners, and non-claims. |
| [`transition-architecture.md`](transition-architecture.md) | Brownfield current pattern, transition posture, Scopecat-owned boundary, and deferred authority map. |
| [`migration-strategy.md`](migration-strategy.md) | Brownfield modernization strategy, migration patterns, and authority-transfer rules. |
| [`migration-roadmap.md`](migration-roadmap.md) | Brownfield design-validation sequence and decision gates. |
| [`risk-register.md`](risk-register.md) | Recurring brownfield risks, mitigation owners, and review triggers. |

## Reading Rules

Start here when a question mentions legacy behavior, existing lab systems,
migration, brownfield adoption, or authority moving from old paths to Scopecat.

Read in this order when aligning migration work:

1. `current-state-assessment.md` for as-is user work patterns, without target
   journey labels.
2. `pain-points.md` for `BR-PAIN-*` workflow friction and opportunities.
3. [`../product/target-journeys.md`](../product/target-journeys.md) for the
   canonical journey/use-case index.
4. [`transition-architecture.md`](transition-architecture.md) for the
   current-pattern to transition-boundary posture.
5. `migration-strategy.md` for coexistence phases, modernization patterns, and
   authority-transfer rules.
6. `migration-roadmap.md` for design-validation sequence. Actual adoption may
   start from any high-value pain point, but the roadmap preserves dependency
   and authority order.
