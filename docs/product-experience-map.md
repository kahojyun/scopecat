# Product Experience Map

## Status

Drafting experience map.

This document describes cross-journey experience shape. It is not a product
plan, roadmap, capability map, subsystem spec, API contract, UI spec, storage
design, or prototype scope.

## Purpose

Give future journey work one durable place to describe the fuller product
experience without making any one `JC-###` too broad to validate.

Earlier documents intentionally kept `JC-001` and `JC-002` narrow enough for
fixture-scale validation. That left some complete-experience pressure scattered
across tracker rows, top-level pain narratives, future-pressure notes, and
journey non-goals.

```text
complete experience pressure
  -> journey-sized validation slice
  -> fixture/prototype boundary
  -> later contract or decision only when earned
```

## Experience Shape

Project-level product direction and boundaries are owned by
[`vision.md`](vision.md). This map only shows how validated and candidate
journeys may compose into a fuller user experience.

One representative long-form experience is:

```text
experiment user prepares work
  -> previews intended scan or method shape
  -> runs measurement in an existing local stack
  -> later opens an existing run or work bundle
  -> sees source identity, selected context, code references, companion
     artifacts, missing facts, conflicts, and sharing boundaries
  -> selects valuable runs or a run group
  -> creates an immutable pre-analysis handoff snapshot
  -> opens the snapshot offline on an analysis computer
  -> compares current evidence with a known-good reference when trust is weak
  -> links later figures, reports, fits, or claims back to source evidence
```

The silhouette is useful because it shows why small slices need to compose. It
does not mean every step is accepted product direction today.

## Experience Step Labels

Use these labels for experience steps. They are not accepted capability
contracts or project-level boundaries by themselves.

| Mode | Meaning | Current examples |
| --- | --- | --- |
| Evidence-only | Read existing artifacts, preserve roles, relations, ambiguity, conflicts, missing facts, and sharing labels. | `JC-001` passive evidence view. |
| Packaging-only | Copy or manifest already-known artifacts and context without producing new analysis outputs. | `JC-002` handoff snapshot export concept. |
| Preview-only | Render intended work shape without hardware apply, scheduling, runner control, or authoritative parameter ownership. | Candidate `JC-007` scan plan preview/diff. |
| Diagnostic-only | Compare evidence, gaps, and confidence signals without selecting truth, restoring state, or mutating systems. | Candidate `JC-009` known-good comparison. |
| Gap-review-only | Explain which scientific or context differences may matter without automatic equivalence scoring. | Candidate `JC-010` comparability review. |
| Proposal-only | Show a proposed change and its evidence before mutation. | Candidate `JC-003` calibration review before write-back. |
| Apply or execution boundary | Mutation, authoritative state changes, and managed execution need explicit future decisions. | Device apply, rollback, managed execution, remote execution, autonomous scheduling. |

## Journey Coverage

- `JC-001` covers post-run explanation of an existing run or work bundle.
- `JC-002` covers selected-run analysis handoff.
- Candidate `JC-007` may cover pre-run scan or method intent.
- Candidate `JC-009` may cover known-good diagnostic comparison.
- Candidate `JC-010` may cover scientific comparability review.
- Later analysis-lineage work may cover figures, reports, fits, and claims.

Adjacent steps are context, not prototype scope. The tracker owns current
phase, priority, and coordination status; owning `JC` documents own validation
boundaries.

## Uncovered Experience Gaps

These gaps help place future `JC` work in the larger experience. They are not
priorities, requirements, or prototype scope.

- Live inspection or live preview before and during a run.
- Measurement-time decision support for long-running measurements, where completed
  sweep slices can trigger fit, quality, anomaly, and intent-specific feedback
  from explicitly recorded measurement data without taking over hardware
  control.
- Declared setup, sample, topology, or schema context when it powers lookup,
  calculation, visualization, comparison, handoff, or diagnostics.
- Analysis-impact lineage from figures, reports, fits, and claims back to
  source runs, code, context, corrections, exclusions, and unresolved ambiguity.
- Failure, interruption, manual intervention, and recovery evidence that helps
  users understand partial or rescued work.
