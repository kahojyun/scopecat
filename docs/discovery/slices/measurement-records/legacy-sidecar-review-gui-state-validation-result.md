# Legacy Sidecar Review GUI State Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Legacy Sidecar Review GUI State**.

It does not define GUI components, execute actions, perform backend lookup,
observe files, accept legacy imports, mutate storage, write records, repair
references, write parameters, decide measurement validity, or make review
state run-blocking.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_sidecar_review_gui_state/basic_view/`](../../../../tests/fixtures/legacy_sidecar_review_gui_state/basic_view)

Implementation candidate:
[`../../implementation_candidates/legacy_sidecar_review_gui_state/`](../../../../implementation_candidates/legacy_sidecar_review_gui_state)

The fixture consumes an already-built
[`legacy-sidecar-post-run-review-validation-result.md`](legacy-sidecar-post-run-review-validation-result.md)
summary and projects it into passive local view state.

The projection exposes:

- lifecycle, legacy-locator, primary-data, and supporting-evidence cards;
- visible review findings;
- possible next action labels such as locator inspection, file-backed locator
  observation, adapter-import review, and finding review;
- explicit view effects showing those actions were not executed.

## What This Earned

The implementation candidate shows that Scopecat can:

- turn a prior local sidecar post-run review into deterministic GUI, CLI, or
  notebook-ready cards;
- show locator and lifecycle attention without treating review state as a run
  gate;
- expose adapter-import or file-observation affordances as labels only;
- carry review findings into a visible list without approving repair, import,
  storage mutation, or measurement-validity decisions;
- reject policies that claim action execution, file observation, import
  acceptance, storage mutation, record writes, reference repair, parameter
  write-back, measurement validity, run blocking, or GUI schema ownership.

## Boundary

This slice validates passive view-state projection only.

It does not:

- create a GUI component contract or shared GUI schema;
- click, invoke, or execute any action;
- open files or query legacy backends;
- normalize, import, or copy legacy data;
- append durable measurement-record state;
- repair locators or discover moved references;
- apply parameter or calibration updates;
- decide measurement validity, scientific quality, run safety, or
  continuation behavior.

## Result

This slice separates two concerns:

1. legacy sidecar post-run review decides what local review facts are visible;
2. legacy sidecar GUI state decides how those facts can be passively surfaced
   as cards and action labels.

That keeps GUI review surfaces from becoming hidden workflow engines. A user
can see where to go next, but a separate slice must own any concrete
observation, import, repair, storage, or execution behavior.

## Follow-Up

Likely follow-up slices should stay separate:

- source observation for an explicitly selected file-backed locator;
- locator repair or moved-reference review without automatic discovery by
  default;
- adapter-authored import review when the user wants normalized primary data;
- durable append of reviewed sidecar facts to measurement-record storage;
- a concrete product GUI only after route-local view-state needs stabilize.
