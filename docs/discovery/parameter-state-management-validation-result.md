# Parameter State Management Validation Result

## Status

Fixture validation result.

This is not an ADR, final parameter schema, branch/tag/commit model, hardware
write-back contract, schema migration contract, setup binding model, device
registry model, GUI design, or shared domain model.

## Inputs

- [`problem-briefs/parameter-state-history.md`](problem-briefs/parameter-state-history.md)
- [`parameter-state-management-validation-plan.md`](parameter-state-management-validation-plan.md)
- `tests/fixtures/parameter_state_management/seed_review_commit/`
- `<sample>/_research/parameter-files-and-artifacts.md`
- `<sample>/_research/parameter-mutation-workflows.md`
- `<sample>/_research/parameter-lineage-schema-pressure.md`

## Validated Boundary

The first fixture validates a narrow parameter-state management boundary:

- parameter state is first-class lab state, not only measurement metadata;
- a named state lineage can group related parameter states without accepting
  final branch/tag/commit semantics;
- `working_point` is a domain purpose label on a lineage, not the generic
  branching concept;
- a copied seed state can be useful while still being incomplete and not fully
  trusted;
- trusted calibrated history should distinguish accepted entries from seeded,
  incomplete, excluded, or exploratory values;
- a draft edit is not durable history by itself;
- an accepted reviewable diff can create the next committed parameter state;
- a reviewable diff can include a small added parameter without earning general
  schema migration;
- a measurement can reference the parameter state selected at start without
  claiming current hardware state.

## Domain Review Result

The fixture matches the desired near-term interpretation: it represents the
parameter-state objects and transitions involved in a small calibration segment,
not the whole calibration workflow.

The sample evidence should inform realism but not define the target model.
Existing code often mutates live `parameters.json` directly, copies run
snapshots, and uses checkpoint/diff/reset helpers that still overwrite live
state. Scopecat should not inherit that live JSON overwrite model as the
desired product boundary.

The setup-binding clarification is important:

- device registry is closer to station or lab configuration;
- setup binding maps sample/cooldown logical entities to physical wiring,
  channels, and devices;
- setup binding is separate from parameter state because it describes physical
  wiring rather than calibrated values;
- setup binding may later need snapshots, simple diffs, and measurement
  references;
- binding changes may require attention because they can imply parameter
  retuning, but they do not automatically invalidate parameter state.

## What The Fixture Can Answer

The expected output can answer:

- which lineage a parameter state belongs to;
- what purpose label that lineage carries;
- why the seed state is not trusted calibrated truth;
- which values changed or were added;
- which review accepted the change;
- which committed state resulted;
- which state a measurement selected at start;
- why current hardware state and write-back remain out of scope.

## Remaining Questions

- What final vocabulary should replace or formalize branch/tag/commit-like
  analogies?
- What trust/readiness states are actually needed beyond the fixture's
  `seeded_incomplete`, `partially_calibrated`, `not_fully_trusted`, and
  `trusted_for_declared_scope`?
- How should trusted entries be selected for drift/history plots?
- When should added/removed parameters become schema migration work rather than
  ordinary reviewable diff entries?
- Should setup binding become the next adjacent slice, or should parameter
  state continue toward a small implementation candidate first?
- How should rollback-like selection work without implying hardware mutation?

## Not Earned

This validation does not earn:

- final parameter schema;
- final branch, tag, commit, merge, rebase, or rollback model;
- automatic proposal branch creation;
- durable history for unapplied drafts;
- schema migration for added, removed, or table-shaped parameters;
- drift plotting;
- hardware write-back or instrument state tracking;
- external JSON authority or external JSON change tracking;
- device registry model;
- setup binding schema, snapshots, or diffs;
- physical wiring model;
- GUI design;
- implementation candidate;
- shared domain model extraction.

## Current Recommendation

Stop this slice at fixture validation unless the next task needs executable
behavior around parameter-state summaries.

If continuing parameter state, the next step should be a tiny side-effect-free
summary candidate for this one fixture only. If comparing broader product
scope, the next adjacent slice should likely be setup binding, because it
connects device registry evidence, sample/cooldown wiring, measurement
references, and parameter retuning pressure.
