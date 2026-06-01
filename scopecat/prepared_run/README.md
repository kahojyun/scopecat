# Prepared Run Module

Local engineering prototype module for prepared-run review composition.

This module is the accepted implementation boundary for the first narrow
prepared-run surface: the manual pre-run review gate. The promoted boundary is
owned by
[`../../docs/architecture/prepared-run/engineering-prototype-promotion-decision.md`](../../docs/architecture/prepared-run/engineering-prototype-promotion-decision.md).

The module composes explicit prior review summaries for prepared-run context,
parameter-state gate, scope alignment, environment review, and optional
environment-operation review evidence. It validates prepared-run-context
continuity, preserves child findings, and returns a local review projection for
manual pre-run review.

The acknowledgement layer is an adjacent local review boundary over an existing
`PreparedRunReviewGateResult` or raw gate summary. It records operator-declared
acknowledgements for selected review items and findings, then projects a local
continuation summary. Acknowledgements can show that non-required review items
have been handled for manual continuation, but they do not repair missing
required context or grant execution authority.

The output posture is local `review_summary` / local review projection. It is
not a portable, public, or export artifact.

It does not own prepared-run context construction, parameter-state storage,
scope alignment, environment review, environment operation execution, runtime
readiness, hardware readiness, parameter write-back, scheduler behavior,
automatic run start, restore behavior, GUI persistence, portable/export output,
or shared run-context schemas.

## API Surface

Current local surface:

- `PreparedRunReviewGateRequest.from_dict(...)`;
- `compose_prepared_run_review_gate(...)`;
- `PreparedRunReviewGateResult.to_dict()`;
- `build_prepared_run_review_gate_summary(...)` as the raw-dictionary adapter.
- `PreparedRunAcknowledgement.from_dict(...)`;
- `PreparedRunAcknowledgementReviewRequest.from_gate_result(...)`;
- `PreparedRunAcknowledgementReviewRequest.from_summary(...)`;
- `compose_prepared_run_acknowledgement_review(...)`;
- `PreparedRunAcknowledgementReviewResult.to_dict()`;
- `build_prepared_run_acknowledgement_summary(...)` as the raw-dictionary
  adapter.

The typed request/result objects are route-local engineering objects. The raw
dictionary adapter exists at the edge for fixture parity and current callers.
Modules with leading underscores are private implementation details.
