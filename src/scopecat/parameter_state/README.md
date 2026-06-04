# Parameter State Prototype

## Status

This route-local module contains the active parameter-state prototype code.

Implementation ownership is tracked in
[`../../../docs/engineering/implementation-register.md`](../../../docs/engineering/implementation-register.md).

The accepted boundary is intentionally narrow:

```text
adapter-authored import preview
  -> explicit human review/commit summary
  -> approved storage writer
  -> explicit manifest/receipt read view
  -> optional source-agnostic read projection
```

The prototype preserves typed adapter and calibration provenance as local
review facts. It does not parse legacy parameter files, write compatibility
files, apply parameters to hardware, inspect current instrument state, perform
live write-back, discover catalogs, migrate schemas, start runs, mutate setup
bindings, or define shared parameter/run-context schemas.
It does not own all parameter management, parameter history, setup truth,
run-preparation workflow, or hardware-apply workflows.

Each live API accepts raw dictionaries at the edge for compatibility with the
existing fixture corpus, immediately validates them into route-local typed
request objects, and returns route-local typed result summaries projected back
to dictionaries. The typed objects are intentionally module-local engineering
boundaries, not a stable public SDK or shared schema.

Storage reads and writes are caller-rooted and path-explicit. The writer uses
no-overwrite behavior for a reviewed managed parameter-state summary. Read
views only open declared manifest and receipt files and compare checksum and
size facts; they do not repair storage or scan for alternatives.

## API Surface

Current route-local surface is grouped by workflow stage.

Adapter-authored intake and review:

- `build_adapter_authored_parameter_state_import_preview_summary(...)`
- `build_adapter_parameter_import_review_commit_summary(...)`

Storage and read views:

- `write_parameter_state_storage(...)`
- `read_parameter_state_storage_view(...)`
- `read_source_agnostic_parameter_state_view(...)`

These functions are the top-level route-local exports. They accept and return
route-local summary dictionaries for the current prototype boundary. They are
not stable public SDK functions or shared schema contracts. Direct submodules
are implementation details unless they are exported from `scopecat.parameter_state`.

## Artifact Boundaries

Parameter-state storage is caller-rooted and path-explicit. Current accepted
storage artifacts are local manifests and receipts written under caller-owned
storage roots.

Current accepted review artifacts are read-view summaries and
source-agnostic review projections. They are local review/storage surfaces, not
portable handoff artifacts, package-shaped outputs, or public reports unless a
later decision explicitly promotes them.

Repository fixtures for this module need repository-safety review. Runtime
redaction is required only if future work turns one of these summaries into a
portable/export boundary.

## Historical Context

Historical candidates remain validation evidence, not runtime dependencies for
this module. The live route-local boundary is the top-level
`scopecat.parameter_state` export surface listed above plus the accepted
prototype boundary in
[`../../../docs/engineering/prototype-boundaries/parameter-state.md`](../../../docs/engineering/prototype-boundaries/parameter-state.md).
