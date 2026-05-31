# Measurement Record Review Inbox Candidate

Side-effect-free product-shape candidate for grouping explicit measurement
record review facts into a local review inbox.

The candidate consumes a fresh operator-review summary plus saved
operator-review receipt summaries and returns only an `internal_validation_summary`
shape. It does not scan storage, open records, discover receipts, refresh read
models, approve actions, mutate records, persist GUI state, or produce a
public/export artifact.
