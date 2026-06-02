# Parameter-State Discovery Track

## Status

Discovery track index with accepted engineering-prototype handoff.

The live implementation boundary is owned by
[`src/scopecat/parameter_state/README.md`](../../../../src/scopecat/parameter_state/README.md)
and the active prototype-boundary note in
[`docs/engineering/prototype-boundaries/parameter-state.md`](../../../engineering/prototype-boundaries/parameter-state.md).
Discovery validation results remain supporting evidence, not live API
contracts.

## Discovery Evidence Summary

Use the implementation register and module README for current live ownership.
This table records discovery-to-prototype status only.

| Slice Area | Discovery Status |
| --- | --- |
| Adapter-authored parameter import preview | Promoted as a route-local deterministic review summary. |
| Adapter import review/commit | Promoted with explicit human acceptance and managed-state projection; no storage mutation. |
| Adapter-derived storage writer | Promoted as an approved no-overwrite writer under a caller-provided root and declared relative paths. |
| Adapter-derived storage read view | Promoted as an explicit manifest/receipt read view with checksum and continuity findings. |
| Source-agnostic read view | Promoted for explicit adapter-derived and calibration-derived manifest/receipt references while preserving typed provenance payloads. |
| Selection context | Promoted as side-effect-free context selection facts; intent labels are review semantics, not lifecycle states. |
| Run-preparation consumption and review chain | Promoted as parameter-state-local manual pre-run review composition over prior read-view facts, gate facts, and scope alignment findings. This does not imply a live prepared-run route owner. |
| Compatibility-file writer | Discovery evidence only; requires a separate decision. |
| Hardware apply and live external write-back | Discovery evidence only; explicitly out of scope. |

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
