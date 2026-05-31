# Measurement Record Review Inbox Validation Result

## Status

Product-shape fixture validation with implementation candidate.

This is not an ADR, GUI implementation, dashboard backend, storage index,
canonical review-state model, action-approval workflow, read-model refresh
workflow, record repair workflow, import workflow, or public/export artifact.
It records the minimal product-shape boundary that the current review-inbox
fixture exercises and where the boundary should remain narrow.

Artifact posture: fixture inputs are repository-safe synthetic fixtures, and
expected/candidate outputs declare `internal_validation_summary`. They are not
portable/public export artifacts or user documentation.

## Inputs

- [`creation-lifecycle-decision.md`](../../../architecture/measurement-records/creation-lifecycle-decision.md)
- `tests/fixtures/measurement_record_review_inbox/basic_workspace/`
- `implementation_candidates/measurement_record_review_inbox/`

## Validated Boundary

The fixture validates a side-effect-free product-shape projection for a first
local measurement-record review inbox.

The input combines:

- one fresh operator-review summary with projected-record catalog facts,
  running-inspection facts, and review findings, produced directly or through
  the explicit operator-review-run adapter;
- one saved operator-review receipt summary for continuation, accepted in the
  real receipt-summary output shape or the candidate-local normalized shape;
- explicit policy fields that keep storage scanning, record opening, record
  mutation, read-model refresh, action approval, GUI persistence, and public
  export out of scope.

The expected summary groups explicit review facts into five lanes:

- `continue_later` for saved receipt summaries that remain active continuation
  prompts;
- `needs_review` for current review findings;
- `running` for declared running-inspection summaries;
- `ready` for current catalog entries;
- `reviewed` for saved receipt summaries already marked reviewed, without
  creating attention prompts.

This validates product language and state grouping only. It does not define a
persisted GUI model, query backend, inbox database, record index, refresh
workflow, or repair action.

## Important Separations

- Saved review receipts create continuation prompts, not retry or action
  authority.
- A current finding can coexist with a saved continuation prompt for the same
  record. The fixture keeps that duplication visible rather than resolving it
  into a canonical state.
- `needs_review` means attention is required; it does not mean the record is
  invalid, repairable, or blocked.
- `running` means a declared running-inspection summary is visible; it does not
  imply a live monitor, subscription, or hardware state.
- `ready` is a local review lane over current catalog facts, not a guarantee
  that the record is scientifically valid or globally complete.

## Implementation Candidate

The implementation candidate builds the `candidate_summary` from explicit
fixture input only. Its standard is deliberately lower than production
operator-review and receipt code: it guards the product-shape boundary and
repository-safe fixtures without re-proving every storage, catalog, receipt, or
review posture invariant. It validates:

- exact policy posture;
- real operator-review output projection into the compact inbox input shape;
- exact operator-review policy/non-claim posture before projecting real review
  output;
- real saved-receipt summary normalization into the compact inbox input shape;
  real summaries must preserve their expected local non-claim posture;
- private minimal boundary helpers for saved review summaries, saved
  selected-record posture, review-only next actions, code-aware review finding
  targets, and visible record references, without extracting a shared
  Measurement Record domain model;
- real running-inspection review actions in the running lane, including
  continuing monitoring and reviewing running-inspection findings;
- path-shaped missing-read-model findings for records without a current catalog
  entry, projected as `not_visible` while carrying the record directory;
- record-local path-shaped findings attached to visible records without
  accepting malformed nested read-model paths;
- catalog entries with embedded read-model review finding counts, kept visible
  as `needs_review` items when no separate finding object is available;
- public-safe workspace, record, receipt, and finding identifiers;
- relative record and receipt paths;
- saved receipt paths constrained to `operator-reviews/`;
- unique visible record ids and receipt ids;
- saved receipt selected-record visibility, including stale continuation prompts
  whose selected record is not currently visible, and no-selection receipts
  preserved as `not_selected`;
- consistent saved selected-record posture: no-selection receipts must keep
  both selected id and source null, while selected records must use a supported
  saved source;
- review findings referencing visible records or explicitly marked not-visible
  selected-record findings;
- representative path-shaped review finding targets at visible record-local
  boundaries, with non-visible path derivation limited to supported
  missing-read-model targets;
- review/navigation-only `next_action` values, without refresh/import/repair
  authority;
- saved receipt summaries using a narrower review action allowlist than
  inbox-generated ready-lane actions;
- non-negative row/count facts.

It remains side-effect free. Production code remains responsible for deeper
posture recomputation, selected-record consistency, catalog source validation,
and detailed finding derivation. The candidate does not scan storage, open
receipts, open records, refresh read models, approve actions, write state, or
render a GUI.

## What The Fixture Can Answer

The current summary can answer:

- which records would appear ready in a first local review inbox;
- which running records should remain visible as current state;
- which current records need review attention;
- which saved receipt prompts should let an operator continue later;
- which attention categories are present without granting mutation or action
  authority.

## Still Not Earned

This validation does not earn:

- live GUI components or navigation behavior;
- canonical cross-session review-state storage;
- dashboard backend or query/index API;
- record discovery beyond explicit input;
- saved receipt discovery;
- automatic read-model refresh;
- record repair, mutation, import, retry, or action approval;
- public/export inbox artifacts.

## Remaining Risks

- The fixtures are synthetic and small by design. They cover one normalized
  product-shape fixture and one real-shape boundary fixture with a real
  operator-review input, path-shaped missing-read-model finding,
  running-inspection review action, and saved receipt summaries for
  no-selection continuation and a reviewed stale missing selection. They are
  not intended to exhaustively mirror every production operator-review edge
  case.
- Lane duplication is unresolved product pressure. A future UI may need to
  choose whether a record with both current findings and saved continuation
  appears in multiple lanes or as one enriched card.
- The candidate assumes explicit summaries are already available. It does not
  validate how a product session discovers receipts or decides freshness.

## Slice Recommendation

Use this as the current stop point for operator-review product-shape work. The
next useful step is either a user-facing sketch over this lane model or a
narrow receipt-discovery/freshness validation if continuing saved review work
requires knowing which receipts to show. Do not start GUI implementation,
canonical review-state persistence, automatic refresh, record repair, or
action approval from this slice alone.
