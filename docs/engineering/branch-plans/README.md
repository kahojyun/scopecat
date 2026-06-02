# Engineering Branch Plans

## Status

Current engineering branch-plan index.

## Purpose

Branch plans capture short-lived implementation scope before code, tests, and
accepted prototype boundaries are updated together. They are useful when the
workflow map names a gap but the exact API, ownership split, artifact boundary,
and test shape are not yet accepted.

Use branch plans for active execution planning. Use
[`../workflow-validation-map.md`](../workflow-validation-map.md) for workflow
state, [`../implementation-register.md`](../implementation-register.md) for
live owners, and [`../prototype-boundaries/README.md`](../prototype-boundaries/README.md)
for accepted live boundaries.

## Current Plans

| Plan | Use For |
| --- | --- |
| [`selected-record-handoff-export.md`](selected-record-handoff-export.md) | Plan the selected stored Measurement Record to single-measurement handoff package export seam. |

## Update Rule

Retire or archive a branch plan when its implementation lands and the accepted
module README, prototype-boundary note, tests, fixtures, and expected outputs
own the behavior.
