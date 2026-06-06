# Brownfield

## Status

Brownfield architecture and migration documentation.

## Purpose

Brownfield docs describe the existing lab-system reality Scopecat is designed
around, the transition architecture between that reality and target Scopecat
journeys, and the migration strategy for moving authority one boundary at a
time.

These docs are internal product and architecture memory. They are not public
user documentation, discovery slice evidence, implementation plans, or task
queues.

## Documents

| Document | Use For |
| --- | --- |
| [`current-state-assessment.md`](current-state-assessment.md) | As-is lab workflow and artifact patterns observed from the local sample corpus and discovery evidence. |
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
2. [`../product/target-journeys.md`](../product/target-journeys.md) for the
   canonical journey/use-case index.
3. [`transition-architecture.md`](transition-architecture.md) for the
   current-pattern to transition-boundary posture.
4. `migration-strategy.md` for coexistence phases, modernization patterns, and
   authority-transfer rules.
5. `migration-roadmap.md` for design-validation sequence. Actual adoption may
   start from any high-value pain point, but the roadmap preserves dependency
   and authority order.
