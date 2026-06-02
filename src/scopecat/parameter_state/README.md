# Parameter State Engineering Prototype

## Status

This route-local module promotes the accepted parameter-state discovery
candidates into production-shaped prototype code.

The accepted boundary is intentionally narrow:

```text
adapter-authored import preview
  -> explicit human review/commit summary
  -> approved storage writer
  -> explicit manifest/receipt read view
  -> optional source-agnostic read projection
  -> parameter-state-local run-preparation consumption and review chain
```

The prototype preserves typed adapter and calibration provenance as local
review facts. It does not parse legacy parameter files, write compatibility
files, apply parameters to hardware, inspect current instrument state, perform
live write-back, discover catalogs, migrate schemas, start runs, mutate setup
bindings, or define shared parameter/run-context schemas.

Each live API accepts raw dictionaries at the edge for compatibility with the
existing fixture corpus, immediately validates them into route-local typed
request objects, and returns route-local typed result summaries projected back
to dictionaries. The typed objects are intentionally module-local engineering
boundaries, not a stable public SDK or shared schema.

Storage reads and writes are caller-rooted and path-explicit. The writer uses
no-overwrite behavior for a reviewed managed parameter-state summary. Read
views only open declared manifest and receipt files and compare checksum and
size facts; they do not repair storage or scan for alternatives.

Run-preparation composition consumes prior read-view facts inside this
parameter-state route. The gate and scope alignment summaries classify review
state for manual pre-run review only; a ready chain is not execution
permission, does not imply a live prepared-run route owner, and carries no
hardware-safety claim.

## API Surface

Current route-local surface:

- `build_adapter_authored_parameter_state_import_preview_summary(...)`
- `build_adapter_parameter_import_review_commit_summary(...)`
- `write_parameter_state_storage(...)`
- `read_parameter_state_storage_view(...)`
- `read_source_agnostic_parameter_state_view(...)`
- `build_parameter_state_selection_summary(...)`
- `build_prepared_run_source_agnostic_parameter_state_consumption_summary(...)`
- `build_prepared_run_parameter_state_gate_summary(...)`
- `build_prepared_run_scope_alignment_summary(...)`
- `build_prepared_run_source_agnostic_parameter_state_review_chain_summary(...)`

These functions accept and return route-local summary dictionaries for the
current prototype boundary. They are not stable public SDK functions or shared
schema contracts.

## Artifact Boundaries

Parameter-state storage is caller-rooted and path-explicit. Current accepted
artifacts are local manifests, receipts, read-view summaries, source-agnostic
review projections, selection summaries, and prepared-run review-chain
summaries. They are local review/storage surfaces, not portable handoff
artifacts or public reports unless a later slice explicitly promotes them.

Repository fixtures for this module need repository-safety review. Runtime
redaction is required only if a future slice turns one of these summaries into
a portable/export boundary.
