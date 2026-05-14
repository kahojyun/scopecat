# JC-002 Document Set

## Status

Drafting second-journey record. This is a lightweight promoted owner for
`JC-002`, not an accepted decision, implementation plan, API contract, export
format, storage design, UI spec, or fixture-validated prototype.

## Purpose

Collect the durable analysis-handoff notes that outgrew the previous candidate
note.

`JC-002` covers an internal analysis handoff flow: a user finds valuable
post-run data, selects one or more runs, and creates an immutable pre-analysis
snapshot that can be moved from an experiment-control computer to a personal
analysis computer without losing source identity or essential context.

The snapshot is input to user-run analysis. Generated figures, PDFs, decks,
fit outputs, and publication/report artifacts are separate derived analysis
records or later lineage work.

## Reading Order

| Order | Document | Use for |
| --- | --- | --- |
| 1 | [`jc-002-journey-selection-note.md`](jc-002-journey-selection-note.md) | Why `JC-002` has been promoted from candidate note to drafting journey record. |
| 2 | [`jc-002-handoff-snapshot-definition.md`](jc-002-handoff-snapshot-definition.md) | Current definition of a handoff snapshot, context tiers, status semantics, and exclusions. |
| 3 | [`jc-002-analysis-handoff-journey.md`](jc-002-analysis-handoff-journey.md) | Current-state and future-state journey seed for selected-run analysis handoff. |

## Current Boundary

This document set may define:

- user-visible handoff pressure;
- current-state evidence patterns;
- the pre-analysis handoff snapshot concept;
- expected local offline consumer surfaces, such as a GUI and Python reader API,
  at validation-goal level;
- required manifest slots with explicit missing-value statuses;
- likely fixture shape and validation questions;
- non-goals and deferred scope.

This document set must not define:

- package manifest schema details;
- reader API signatures or final GUI behavior;
- internal storage model;
- export adapter commitments;
- live-preview monitor semantics;
- managed analysis-script execution;
- permission or redaction systems;
- full publication, report-generation, or ELN workflows.

## Promotion Note

The previous root-level candidate note has been removed. This folder now owns
`JC-002` drafting detail. Keep this set smaller than the `JC-001` folder until
a concrete fixture, prototype, or decision earns additional artifact types.
