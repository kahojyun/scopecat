# Parameter Trusted Drift Projection Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-specific slice for projecting trusted
parameter history from accepted parameter states. It does not accept rendered
drift plotting, final parameter schema, GUI behavior, schema migration,
hardware write-back, rollback automation, external JSON authority, or shared
domain model extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

This slice follows
[`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md).
That first parameter-state candidate validated copied seed states, reviewable
diffs, committed states, trusted entry paths, and measurement start selection.
This slice tests the next boundary: using trusted entries for history review
without plotting untrusted values as calibrated truth.

First fixture:

- `tests/fixtures/parameter_trusted_drift_projection/basic_trusted_history/`

## Validation Question

Can Scopecat project trusted parameter history from eligible committed
parameter states and declared trusted entry paths while excluding copied seed
states, exploratory states, untrusted carried values, and non-scalar
schema-limited entries?

## Evidence Pressure

The sample evidence supports this fixture boundary:

- users need to compare how calibrated values changed after repeated
  calibration;
- copied seed states and dated variants should remain visible but should not
  silently become trusted calibrated history;
- active parameter files often carry values that were not revalidated in the
  current context;
- table-shaped parameter companions show schema pressure that should be
  surfaced as review-needed rather than flattened into scalar history.

## First Fixture Shape

The first fixture should stay small:

- one named parameter state lineage;
- one copied seed state excluded from trusted history;
- two accepted committed states with declared trusted scalar entries;
- one exploratory state excluded from trusted history;
- one untrusted carried scalar value skipped from history;
- one trusted non-scalar entry skipped as schema-limited;
- one side-effect-free drift projection summary that is not a rendered plot.

## Input Boundary

Fixture input may include:

- parameter lineage identity, label, purpose, and target scope;
- parameter states with readiness, trust status, committed time,
  accepted-review references, and history-plot eligibility;
- parameter entries with path, label, value, unit, and trust state;
- declared trusted entry paths;
- a requested projection over explicit state IDs and parameter paths;
- explicit policy claims that rendering, write-back, hardware-state claims,
  and schema migration are not performed.

Fixture input should not include:

- rendered plot artifacts;
- GUI operations;
- live hardware or instrument state;
- hardware write logs;
- external mutable JSON authority;
- schema migration transforms;
- rollback/reset behavior;
- universal parameter schema.

## Expected Output

Expected review output should let a reviewer answer:

- which lineage is being reviewed;
- which states contributed trusted history points;
- which states were excluded and why;
- which parameter paths produced scalar trusted points;
- which untrusted or non-scalar entries were skipped;
- that no plot rendering, hardware write-back, hardware-state claim, or schema
  migration occurred.

## Out Of Scope

This plan does not earn:

- final parameter schema;
- rendered drift plotting;
- GUI design;
- schema migration;
- hardware write-back or instrument state tracking;
- rollback automation;
- external JSON authority;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at side-effect-free trusted-history projection. A later GUI or
plotting slice should consume an accepted projection summary rather than
reopening trust/readiness filtering.
