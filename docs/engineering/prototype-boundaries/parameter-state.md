# Parameter-State Prototype Boundary

## Status

Accepted engineering-prototype boundary.

This is the current live route-local boundary note for the parameter-state
prototype. Live API details belong in
[`../../../src/scopecat/parameter_state/README.md`](../../../src/scopecat/parameter_state/README.md).

## Current Boundary

The active parameter-state prototype lives under
`src/scopecat/parameter_state/`.

The prototype owns these local review and storage surfaces:

- adapter-authored parameter-state import preview;
- explicit adapter import review/commit summary;
- reviewed adapter-derived parameter-state storage writer;
- explicit normalized parameter-state manifest/receipt storage read view.

The prototype keeps the active contracts dictionary-shaped and
route-local at the public edge, but live modules validate into typed
route-local request objects and return typed route-local result summaries
before projecting dictionaries for callers. It does not introduce shared
schemas, shared domain models, or a stable public SDK.

## Out Of Scope

The promotion explicitly does not add:

- hardware apply or current instrument-state claims;
- external compatibility file writing;
- live write-back to source parameter files;
- catalog discovery or storage scan behavior;
- schema migration;
- setup-binding mutation;
- automatic run start;
- separate source-agnostic projection over heterogeneous storage shapes;
- shared parameter, provenance, gate, or run-context schemas.

## Handoff Notes

The storage manifest is the normalization point. Future adapter imports,
calibration handoffs, or other creation paths should produce the same
normalized parameter-state storage shape instead of adding source-specific
read projections.

Repository fixture and expected-output artifact classification remains
`internal_validation_summary`. Runtime redaction is not added because these
fixtures are repository-safe validation artifacts, not portable/public/export
artifacts.
