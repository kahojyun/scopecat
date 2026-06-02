# Parameter-State Route

## Status

Route index with accepted engineering-prototype handoff.

The live implementation boundary is owned by
[`src/scopecat/parameter_state/README.md`](../../../../src/scopecat/parameter_state/README.md)
and the promotion decision in
[`docs/architecture/parameter-state/engineering-prototype-promotion-decision.md`](../../../architecture/parameter-state/engineering-prototype-promotion-decision.md).
Discovery validation results remain supporting evidence, not live API
contracts.

## Promotion Matrix

| Slice Area | Promotion State | Current Owner |
| --- | --- | --- |
| Adapter-authored parameter import preview | Promoted as a route-local deterministic review summary. | `scopecat.parameter_state.import_preview` |
| Adapter import review/commit | Promoted with explicit human acceptance and managed-state projection; no storage mutation. | `scopecat.parameter_state.import_review` |
| Adapter-derived storage writer | Promoted as an approved no-overwrite writer under a caller-provided root and declared relative paths. | `scopecat.parameter_state.storage_writer` |
| Adapter-derived storage read view | Promoted as an explicit manifest/receipt read view with checksum and continuity findings. | `scopecat.parameter_state.storage_read_view` |
| Source-agnostic read view | Promoted for explicit adapter-derived and calibration-derived manifest/receipt references while preserving typed provenance payloads. | `scopecat.parameter_state.source_agnostic_read_view` |
| Selection context | Promoted as side-effect-free context selection facts; intent labels are review semantics, not lifecycle states. | `scopecat.parameter_state.selection_context` |
| Run-preparation consumption and review chain | Promoted as parameter-state-local manual pre-run review composition over prior read-view facts, gate facts, and scope alignment findings. This does not imply a live prepared-run route owner. | `scopecat.parameter_state.prepared_run_*` |
| Compatibility-file writer | Not promoted. Requires a separate decision. | Discovery evidence only. |
| Hardware apply and live external write-back | Not promoted. Explicitly out of scope. | No implementation owner. |

## Route Boundary

The accepted route-local prototype keeps mutable hardware and external files
outside Scopecat authority. A stored parameter state can be reviewed and
selected for run-preparation context, but that selection does not apply values
to instruments, rewrite source JSON/XLSX files, invalidate current hardware
state, imply a live prepared-run route owner, or grant run-start permission.

Prepared-run and calibration handoff summaries should carry narrow identities,
trusted-entry counts, typed provenance, and review finding codes. They should
not expose storage internals beyond declared manifest/receipt read facts
needed for review continuity.
