# Parameter State Selection Context Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-specific slice for representing parameter
state selection as a context input reference. It does not accept a final
parameter schema, rollback model, branch/tag/commit semantics, hardware
write-back, run execution, GUI behavior, or shared domain model extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

This slice follows
[`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md).
That first parameter-state candidate validated first-class parameter states,
committed states, trusted entry paths, reviewable changes, and measurement
start selection. This slice tests a more general selection boundary: a
parameter state can be selected as a named input for a future context without
making known-good, rollback, branch, tag, or commit semantics part of the
generic model.

First fixture:

- `tests/fixtures/parameter_state_selection_context/known_good_future_context/`

## Validation Question

Can Scopecat represent selection of a parameter state as a context input
reference, carrying scenario-specific intent such as previous-known-good reuse
as review semantics, while avoiding hardware write-back, current hardware
state claims, rollback mutation, and branch/tag/commit semantics?

## Evidence Pressure

The sample evidence supports this fixture boundary:

- users need to recover or reuse previous parameter states after exploratory
  or known-bad tuning;
- current workflows often use copied files or reset-like helpers that overwrite
  live parameter JSON, but Scopecat should not inherit live overwrite behavior
  as the generic product boundary;
- a future run preparation may need a selected parameter state input reference
  without claiming that the selected state is currently applied to hardware;
- scenario labels such as known-good, previous working state, or recovery
  baseline are useful for review but should not become universal lifecycle
  states.

## First Fixture Shape

The first fixture should stay small:

- one named parameter state lineage;
- one committed trusted parameter state;
- one later exploratory state that motivates selecting the earlier state;
- one future run-preparation context that declares its selected-state
  requirement;
- one parameter-state selection record with a scenario intent label;
- explicit side-effect claims that no hardware write-back, current
  hardware-state claim, or rollback mutation occurred.

## Input Boundary

Fixture input may include:

- parameter lineage identity, label, purpose, and target scope;
- parameter states with readiness, trust status, accepted-review references,
  entries, and trusted entry paths;
- selection contexts with context kind, target scope, and selected-state
  requirement;
- parameter-state selections with selected state ID, context ID, status,
  scenario intent label, reason, selected time, selected role, and side-effect
  claims;
- explicit policy claims that selection is a context input reference and
  intent labels are not lifecycle semantics.

Fixture input should not include:

- hardware state;
- instrument write logs;
- live external JSON mutation;
- rollback/reset execution;
- branch, tag, commit, merge, or rebase semantics;
- future run execution;
- GUI operations;
- universal parameter schema.

## Expected Output

Expected review output should let a reviewer answer:

- which parameter state was selected;
- which future context consumes the selection;
- what context-owned requirement the selected state satisfies;
- which scenario intent label and reason were recorded for review;
- why the intent label is not a generic lifecycle model;
- that selecting the state does not write hardware, claim current hardware
  state, or perform rollback mutation.

## Out Of Scope

This plan does not earn:

- final parameter schema;
- rollback model;
- branch/tag/commit semantics;
- hardware write-back or instrument state tracking;
- run execution;
- GUI design;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at side-effect-free context-selection summary. Later run
preparation or GUI slices can consume the selected parameter-state reference
without redefining rollback or known-good semantics.
