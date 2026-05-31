# Measurement Record Review Inbox Candidate

Side-effect-free product-shape candidate for grouping explicit measurement
record review facts into a local review inbox.

The candidate consumes an explicit operator-review run or its documented inbox
projection plus saved operator-review receipt summaries, then returns only an
`internal_validation_summary` shape. The explicit adapter is
`project_operator_review_run_for_review_inbox(...)`; it keeps the product shape
from drifting away from the real operator-review output. Saved receipts with
`recorded_for_continuation` enter the attention-driving `continue_later` lane,
while `recorded_as_reviewed` receipts enter a separate non-attention `reviewed`
lane. Real receipt-summary output is normalized at the input boundary before
lane grouping. The candidate uses private minimal boundary helpers for saved
review summaries, review-only next actions, and review finding references so
those meanings are not re-derived at each projection step. These helpers stay
local to the candidate: saved selected-record posture, code-aware review finding
targets, and visible record references are not promoted into a shared
Measurement Record domain model. Inbox `next_action` values are limited to
review/navigation actions and do not represent refresh, import, repair, retry,
or mutation authority. Saved receipt summaries use the narrower saved-review
action allowlist and cannot claim inbox-generated ready-lane actions. Real
running-inspection review actions are accepted as running-lane actions,
record-local path findings can attach to visible records, missing-read-model
finding paths can project to a not-currently-visible record with a carried
`record_dir`, and saved no-selection receipts are preserved as
`record_visibility: not_selected`. Catalog entries with embedded read-model
review finding counts remain visible as needs-review items even when no
separate finding object is available. Saved receipt paths must remain under
`operator-reviews/`, and real receipt summaries must preserve their declared
non-claim posture. It does not scan storage, open records, discover receipts,
refresh read models, approve actions, mutate records, persist GUI state, or
produce a public/export artifact.
