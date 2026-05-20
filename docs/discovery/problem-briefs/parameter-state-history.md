# Parameter State Management

## Status

Evidence-backed problem brief.

## User-Facing Failure

Mutable parameter files, copied seed states, and calibration updates make it
hard to understand which parameter state is believed usable, which state a run
used, how calibrated values changed over time, which working point should be
selected for future work, and which bad or incomplete states should be avoided.

A parameter snapshot is not only measurement metadata. It can represent
first-class lab state that users care about independently of any one
measurement: the currently trusted calibrated state, a seeded but not yet fully
calibrated state, a previous state to reuse, or a working-point branch for a
specific sample or bias configuration.

## Observed Sample Evidence

- Active parameter files exist in parallel project trees, with matching broad
  section shape but different content.
- Backups, dated variants, sample/config-specific subsets, and copied temp
  seeds show lineage-like pressure outside a single current file.
- Active parameter files are copied into run-adjacent snapshots.
- Experiment and calibration code directly overwrites live parameter JSON.
- Historical analysis reads run-scoped parameter snapshots.
- Setting directories contain active files, backups, dated variants, lock
  clues, generated companion files, and run-number snapshots.
- Local parameter manager code shows snapshot, diff, and reset pressure, but
  reset/update still overwrite live parameter JSON and do not validate product
  rollback semantics.
- Table-shaped parameter companions and variants show row, column, group, and
  schema drift pressure.

## Project-Owner Clarification

- Parameter snapshots record calibration-relevant experiment parameters that
  users care about as lab state, not just values attached to measurements.
- Users may want to know how well a sample is currently calibrated, how values
  changed after several days of periodic calibration, which previous state to
  reuse, or which working point should be selected for a measurement.
- A copied parameter file can be a seed for calibration and may contain values
  from another sample. Until calibration is complete, not every value in that
  snapshot should be treated as currently reasonable or trusted.
- Users may need multiple named parameter state lineages. A working point can
  be a domain-specific purpose label on a lineage, especially for sample- or
  bias-configuration-specific states, but exploration, recovery, migration, or
  comparison may also need lineage-like organization.
- Git-like branch, tag, and commit concepts are useful analogies, but they are
  not accepted product vocabulary or semantics yet.
- Starting a measurement may select a branch, tag, or commit-like parameter
  reference. That selected parameter state is not the same as current hardware
  state; instruments are set when the measurement starts.
- The core workflow is closer to snapshot -> edit -> review diff -> commit new
  state than "record every proposed write."
- Unapplied changes should not become durable history by default. A proposal or
  branch-like draft may be useful later, but automatic proposal-branch creation
  could create clutter.
- Reviewable change sets may be useful for calibration workflows: Scopecat can
  compute a diff from a starting snapshot and show it for human confirmation
  before committing a new state.
- Bad states should not be deleted by default. The useful model is closer to
  yank/exclude-from-default-analysis than hard delete.
- External JSON files should probably become migration/import sources or
  compatibility surfaces, not the desired long-term source of authority.
  Reliable parameter history, especially across schema changes, likely needs
  Scopecat-managed parameter state.

## Derived Hypotheses

- A first validation question should test whether Scopecat can represent
  first-class calibrated parameter state as snapshots, named state lineages,
  domain purpose labels, trust/readiness state, and reviewable diffs without
  deciding hardware write-back.
- Run-linked parameter references remain important, but they are links from
  measurements to parameter state, not the only reason the parameter snapshot
  exists.
- Drift/history plots should distinguish trusted calibrated values from seeded,
  incomplete, excluded, or exploratory states so the plotted history is not
  misleading.
- Schema changes such as added/removed parameters or changed table shape are
  real future pressure. Most routine calibration may not need schema changes,
  but exploratory work and experiment redesign can.
- Rollback-like behavior should first mean selecting a previous parameter
  snapshot, branch, tag, or commit-like state for future measurement setup. It
  does not imply mutating current hardware state.

## Out Of Scope For This Brief

- Universal parameter models, final storage format, Scopecat-decided write-back
  ownership, rollback automation, hard-delete policy, and autonomous
  calibration.
- Treating static files as authoritative live hardware or setup truth.
- Final branch/tag/commit vocabulary, merge behavior, automatic proposal branch
  creation, schema migration machinery, table-shape migration, and external
  JSON file tracking.

## Possible Validation Questions

- Can a small fixture represent snapshot -> edit -> review diff -> commit new
  parameter state while keeping hardware write-back out of scope?
- Can parameter state carry readiness or trust status well enough to avoid
  plotting seeded or incomplete calibration states as if they were current
  calibrated truth?
- Can named parameter state lineage and purpose labels be represented without
  prematurely accepting branch/tag/commit semantics or making working point the
  only lineage concept?
- Can a measurement reference the parameter state used at measurement start
  without treating the parameter state as measurement-owned metadata?
- Can added parameters appear in reviewable diffs without requiring full schema
  migration design?
