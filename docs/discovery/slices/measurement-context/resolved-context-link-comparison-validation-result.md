# Resolved Context Link Comparison Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Context Backlog subcase:
**Selected-reference comparison over resolved measurement-record context
links**.

It does not accept a final selected-reference comparison engine, final context
schema, final measurement-record schema, shared relation graph, storage model,
restore contract, hardware-control contract, parameter write-back contract,
setup-mutation contract, environment manager, code execution contract,
workflow DAG, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/resolved_context_link_comparison/basic_selected_reference/`](../../../../tests/fixtures/resolved_context_link_comparison/basic_selected_reference)

Implementation candidate:
[`../../implementation_candidates/resolved_context_link_comparison/`](../../../../implementation_candidates/resolved_context_link_comparison)

The fixture compares a current qA chevron measurement against a user-marked
last-working reference measurement. It compares only actual measurement-record
context links:

- reference parameter state versus current parameter state;
- shared setup binding;
- shared managed code version;
- declared environment context present on the reference and unavailable on the
  current measurement.

Measurement intent selectors are explicitly out of scope. The comparison uses
the snapshots recorded on the measurement records, not prospective selector
rules.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- compare resolved measurement-record context links for a selected reference;
- report changed, same-observed, and missing context findings;
- compare a selected reference using an ordinary user measurement mark;
- keep measurement intent selectors out of the comparison;
- keep context payloads, primary data, fit quality, readiness, and cause
  attribution out of scope;
- reject fixture claims that cross into intent-selector comparison, primary
  data comparison, fit-quality comparison, cause attribution, recursive
  traversal, context import, hardware control, parameter write-back, setup
  mutation, environment sync, code import, or code execution.

## Boundary

This slice validates selected-reference comparison over explicit resolved
context links only.

It does not:

- compare measurement intent selectors;
- compare raw or primary measurement data;
- compare fit quality, plots, user conclusions, or scientific outcomes;
- inspect, import, or interpret context payloads;
- decide why a measurement changed;
- decide whether a run is ready, blocked, safe, reproducible, or scientifically
  valid;
- recursively traverse adjacent records or relation graphs;
- apply parameter state to hardware;
- mutate setup binding;
- sync or validate a runtime environment;
- import, load, or execute selected code;
- restore selected context;
- define a GUI workflow.

## Result

Resolved context links provide a useful selected-reference comparison surface.

The comparison can say that the current measurement used a different parameter
snapshot, the same setup binding, the same managed code version, and no
available declared environment context, without claiming that any of those
facts caused the observed measurement outcome.

The distinction from measurement intent is important: intent selectors remain
prospective and may move, while the selected-reference comparison uses the
retrospective context links recorded on each measurement.

## Follow-Up

Stop this slice at resolved context-link comparison unless a concrete workflow
needs stronger behavior.

Likely follow-up slices should stay separate:

- step-level context-link comparison for calibration steps, if the calibration
  route needs a separate fixture from measurement records;
- context readiness or status summaries only after repeated workflows need
  sharper review vocabulary;
- preview or raw-data comparison, still separate from context comparison and
  cause attribution;
- dynamic selected-reference UX, without changing the underlying comparison
  authority.
