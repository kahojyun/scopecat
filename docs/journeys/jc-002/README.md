# JC-002

## Status

Drafting second-journey record with a fixture-backed prototype slice. This is a
lightweight promoted owner for `JC-002`, not an accepted decision,
implementation plan, API contract, export format, storage design, or UI spec.

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

| Order | Document | Type | Use for |
| --- | --- | --- | --- |
| 1 | [`selection.md`](selection.md) | Selection | Why `JC-002` has been promoted from candidate note to drafting journey record. |
| 2 | [`contracts/handoff-snapshot.md`](contracts/handoff-snapshot.md) | Contract | Current definition of a handoff snapshot, context tiers, status semantics, and exclusions. |
| 3 | [`journey.md`](journey.md) | Journey | Current-state and future-state journey seed for selected-run analysis handoff. |
| 4 | [`prototypes/handoff-snapshot.md`](prototypes/handoff-snapshot.md) | Prototype | Draft fixture and prototype checks for local offline GUI/Python-reader consumption. |

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

The current prototype validation lives in
[`../../../prototypes/jc002_handoff_snapshot.py`](../../../prototypes/jc002_handoff_snapshot.py)
and
[`../../../tests/fixtures/jc002-handoff-snapshot/`](../../../tests/fixtures/jc002-handoff-snapshot/).
It validates the current fixture-scale handoff boundary only. Detailed checks,
hardening notes, and known gaps belong in
[`prototypes/handoff-snapshot.md`](prototypes/handoff-snapshot.md) or the
prototype/test artifacts, not this README.

This document set must not define:

- package manifest schema details;
- reader API signatures or final GUI behavior;
- internal storage model;
- export adapter commitments;
- live-preview monitor semantics;
- managed analysis-script execution;
- permission or redaction systems;
- full publication, report-generation, or ELN workflows.

## Next Decision

Decide whether the current handoff snapshot prototype earns an accepted
fixture-scale boundary, needs another lab scenario, or should feed back into a
small design-pressure ownership review with the `JC-001` ownership pass.

Keep the reasoning, validation boundary, and follow-up detail in this document
set. The project tracker should carry only the phase, links, and compact
cross-journey coordination point.
