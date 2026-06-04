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
| [`transition-architecture.md`](transition-architecture.md) | Current/transition/target journey mapping and ownership posture by target journey. |
| [`migration-strategy.md`](migration-strategy.md) | Brownfield modernization approach, migration patterns, and authority-transfer rules. |
| [`migration-roadmap.md`](migration-roadmap.md) | Use-case-driven migration sequence and decision gates. |
| [`risk-register.md`](risk-register.md) | Recurring brownfield risks, mitigation owners, and review triggers. |

## Reading Rules

Start here when a question mentions legacy behavior, existing lab systems,
migration, brownfield adoption, or authority moving from old paths to Scopecat.

Read in this order when aligning migration work:

1. `current-state-assessment.md` for as-is user work patterns, without target
   journey labels.
2. `target-journeys.md` for user-recognizable target journeys and supporting
   workflows.
3. `migration-strategy.md` for the current-to-target migration model,
   coexistence phases, and authority-transfer rules.
4. `migration-roadmap.md` for design validation sequence. Actual adoption may
   start from any high-value pain point, but the roadmap preserves dependency
   and authority order.

Use product docs for target journeys, adoption strategy, and target
capabilities. Use engineering docs for validation maturity and implementation
ownership.
