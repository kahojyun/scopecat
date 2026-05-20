# Parameter State Management Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a first fixture boundary for parameter state management. It
does not accept final parameter schema, branch/tag/commit semantics, hardware
write-back, schema migration, external JSON tracking, or GUI design.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

These notes should inform fixture realism, not override the cleaner product
boundary. They are evidence of current practice: copied files, direct live JSON
mutation, checkpoint-like helpers, and schema/table drift.

First fixture:

- `tests/fixtures/parameter_state_management/seed_review_commit/`

## Validation Question

Can Scopecat represent first-class calibrated parameter state as snapshots,
state lineages, purpose labels, trust/readiness state, reviewable diffs, and
committed states, without deciding hardware write-back or final version-control
semantics?

## Evidence Pressure

The sample evidence supports the fixture boundary:

- active `parameters.json` files exist in parallel project trees with matching
  broad shape but different content;
- backups, dated variants, sample/config-specific subsets, and copied temp
  seeds show branch-like or lineage-like pressure;
- run-adjacent parameter snapshots capture the parameter state near a
  measurement without making the snapshot measurement-owned state;
- a local `ParamManager` has checkpoint-like `commit()`, read-only `diff()`,
  and rollback-like `reset()`, but reset and update still overwrite the live
  parameter file;
- calibration and analysis notebooks commonly mutate nested parameter fields
  and save the full live JSON state directly;
- review-like comparison exists through diffs and printed diagnostics, but it
  does not appear to gate writes;
- table-shaped companions and parameter variants show row/column, group, and
  schema drift pressure, but broad schema migration is too large for the first
  fixture.

## Concept Boundary

`working point` is not the generic grouping model.

The generic concept under validation is a named parameter state lineage: a
series of related parameter states that users may select for future work,
compare over time, or branch from. A working point can be a domain-specific
purpose label on such a lineage, not the only reason a lineage exists.

Possible lineage purposes include:

- working point;
- exploratory tuning;
- calibration recovery;
- sample setup migration;
- comparison baseline;
- temporary experiment variant.

Git-like branch, tag, and commit language is useful as an analogy, but this
plan does not accept Git semantics such as merge, rebase, detached head,
automatic branch creation, or tag movement.

## First Fixture Shape

The first fixture should stay small:

- one sample or target group;
- one named parameter state lineage;
- a `lineage_purpose` such as `working_point`;
- a seed state copied from another context and marked incomplete, seeded, or
  not fully trusted;
- a draft edit derived from that seed;
- a reviewable diff showing changed and possibly added parameters;
- an accepted commit-like state recorded after review;
- one measurement referencing the selected committed state at measurement
  start.

The fixture may include a single added parameter if that helps test exploratory
schema pressure, but it should not implement schema migration.

## Input Boundary

Fixture input may include:

- saved parameter states with IDs, labels, parent links, lineage IDs, purpose
  labels, and readiness/trust state;
- parameter entries with names, values, units, optional labels, and optional
  schema or group hints;
- draft edits from a known base state;
- reviewable diff entries derived from the draft;
- an accepted committed state;
- measurement reference to the parameter state selected at measurement start.

Fixture input should not include:

- hardware state;
- instrument write logs;
- external mutable JSON authority;
- live `parameters.json` overwrite behavior as the desired product model;
- automatic branch creation;
- merge/rebase semantics;
- GUI operations;
- universal parameter schema.

## Expected Output

Expected review output should let a reviewer answer:

- which lineage the parameter state belongs to;
- what purpose label the lineage carries;
- whether the starting state was trusted, incomplete, seeded, or exploratory;
- which parameters changed, were added, or were removed;
- which reviewed change became the next committed state;
- which measurement selected which parameter state at start;
- that selecting a state for measurement setup is not the same as claiming
  current hardware state;
- that unapplied drafts are not durable history unless accepted.

## Out Of Scope

This plan does not earn:

- final branch/tag/commit model;
- final parameter schema;
- schema migration for added, removed, or reshaped tables;
- automatic proposal branch creation;
- hardware write-back or instrument state tracking;
- external JSON change tracking;
- drift plotting;
- rollback automation;
- conflict resolution;
- GUI design;
- shared domain model extraction.

## Current Recommendation

Review the first fixture before writing any implementation candidate. The first
goal is to validate terminology, trust/readiness state, lineage purpose, and
reviewable diff shape.
