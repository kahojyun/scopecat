# Parameter Write Compatibility Output Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-specific slice for planning external
compatibility output from accepted parameter state. It does not accept a
compatibility-file writer, final parameter schema, external JSON authority,
hardware write-back, schema migration, rollback automation, drift plotting, or
GUI design.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

This slice follows
[`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md).
That first parameter-state candidate validated copied seed states, reviewable
diffs, committed states, and measurement start selection. This slice tests the
next boundary after an accepted review: preparing external compatibility output
without applying changes.

First fixture:

- `tests/fixtures/parameter_write_compatibility_output/basic_output_plan/`

## Validation Question

Can Scopecat prepare an external compatibility output plan from an accepted
committed parameter state while keeping Scopecat-managed parameter state as
the authority and avoiding file writes, hardware write-back, schema migration,
or current instrument-state claims?

## Evidence Pressure

The sample evidence supports this fixture boundary:

- current lab workflows still use active `parameters.json` files and copied
  variants;
- calibration code can directly overwrite live JSON today, but that should not
  become Scopecat's authority boundary;
- external JSON remains useful as a migration or compatibility surface during
  adoption;
- table-shaped parameter companions show schema pressure that should be
  surfaced as skipped or review-needed output, not silently flattened.

## First Fixture Shape

The first fixture should stay small:

- one committed parameter state trusted for declared scope;
- one accepted review that authorized that committed state;
- one planned public-safe relative external compatibility JSON target;
- a few direct scalar entries planned for output;
- one untrusted seed-carried value skipped from output;
- one trusted but schema-limited table-shaped value skipped from output.

## Input Boundary

Fixture input may include:

- committed parameter-state identity, label, readiness, trust status, and
  trusted entry paths;
- parameter entries with values, units, trust, and compatibility state;
- accepted review identity that targets the committed source state;
- compatibility output target path and format;
- explicit output entries with emit or skip state;
- explicit side-effect policy claims.

Fixture input should not include:

- live external JSON contents as authority;
- file write results;
- hardware write logs;
- instrument state;
- setup binding mutation;
- schema migration transforms;
- rollback/reset behavior;
- GUI operations.

## Expected Output

Expected review output should let a reviewer answer:

- which committed parameter state is the source authority;
- which accepted review created the committed source state used by the output
  plan;
- where the public-safe relative external compatibility target would be;
- which entries are planned for output;
- which entries are skipped and why;
- that no file write, hardware write-back, schema migration, or current
  hardware-state claim occurred.

## Out Of Scope

This plan does not earn:

- final parameter schema;
- compatibility file writer;
- external JSON authority;
- hardware write-back or instrument state tracking;
- schema migration;
- rollback automation;
- drift plotting;
- setup-binding invalidation;
- GUI design;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at side-effect-free output planning unless the next task needs
an approved writer. A later writer slice should start from this plan's output
and separately validate path policy, overwrite policy, redaction, checksums,
and failure handling before any real file materialization.
