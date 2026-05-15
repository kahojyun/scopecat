# JC-002

## Status

Draft journey record with a fixture-backed prototype in validation. The
snapshot boundary is draft and not accepted.

This is not an accepted decision, implementation plan, API contract, export
format, storage design, or UI spec.

## Purpose

`JC-002` covers internal analysis handoff: a user finds valuable post-run data,
selects one or more runs, and creates an immutable pre-analysis snapshot that
can move from an experiment-control computer to a personal analysis computer
without losing source identity or essential context.

Generated figures, PDFs, decks, fit outputs, and publication/report artifacts
are separate derived analysis records or later lineage work. They are not part
of the first handoff snapshot boundary.

## Reading Order

| Order | Document | Use for |
| --- | --- | --- |
| 1 | [`journey.md`](journey.md) | User situation, current-state pain, future-state flow, and journey-level acceptance checks. |
| 2 | [`snapshot-boundary.md`](snapshot-boundary.md) | Draft snapshot boundary: included context, excluded outputs, safety invariants, and missing-value semantics. |
| 3 | [`prototypes/handoff-snapshot.md`](prototypes/handoff-snapshot.md) | Fixture-backed validation result and remaining prototype questions. |
| 4 | [`selection.md`](selection.md) | Historical note on why this candidate was promoted. |

## Current Boundary

The canonical draft snapshot boundary lives in
[`snapshot-boundary.md`](snapshot-boundary.md). Other documents in this folder
summarize that boundary only.

This document set may validate a fixture-scale analysis handoff boundary. It
must not define final package schema, reader API, storage, GUI, export adapter,
permission system, managed analysis execution, or publication workflow.

The current prototype validation lives in
[`../../../prototypes/jc002_handoff_snapshot.py`](../../../prototypes/jc002_handoff_snapshot.py)
and
[`../../../tests/fixtures/jc002-handoff-snapshot/`](../../../tests/fixtures/jc002-handoff-snapshot/).

## Next Decision

Decide whether the current handoff snapshot prototype earns an accepted
fixture-scale boundary or needs another lab scenario first. Keep the reasoning
in this folder; the project tracker should carry only phase, links, and compact
cross-journey coordination.
