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
lane grouping. Inbox `next_action` values are limited to review/navigation
actions and do not represent refresh, import, repair, retry, or mutation
authority. It does not scan storage, open records, discover receipts, refresh
read models, approve actions, mutate records, persist GUI state, or produce a
public/export artifact.
