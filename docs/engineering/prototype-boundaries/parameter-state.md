# Parameter-State Engineering Prototype Promotion Decision

## Status

Accepted engineering-prototype boundary.

This is the current live route-local boundary note for the parameter-state
prototype. Live API details belong in
[`../../../src/scopecat/parameter_state/README.md`](../../../src/scopecat/parameter_state/README.md).

## Decision

Promote the accepted parameter-state discovery candidates into a route-local
engineering prototype under `src/scopecat/parameter_state/`.

The prototype owns these local review and storage surfaces:

- adapter-authored parameter-state import preview;
- explicit adapter import review/commit summary;
- reviewed adapter-derived parameter-state storage writer;
- explicit adapter manifest/receipt storage read view;
- source-agnostic adapter/calibration read-view projection;
- parameter-state selection-context summary;
- parameter-state-local run-preparation consumption over source-agnostic
  parameter-state facts;
- parameter-state-local pre-run gate, scope alignment, and review-chain
  composition.

The promoted code keeps the candidate contracts dictionary-shaped and
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
- shared parameter, provenance, gate, or run-context schemas.

## Handoff Notes

The source-agnostic read view is the route-local handoff for downstream
prepared-run and calibration-continuation review. It accepts explicit
adapter-derived and calibration-derived manifest/receipt references, preserves
typed provenance payloads, and reports checksum or continuity mismatches as
review findings.

Run-preparation consumption must use prior read-view facts. A clean
consumption summary can still produce a review-chain `needs_review`
classification when scope alignment finds partial target coverage; that is a
parameter-state-local review state, not an execution permission or evidence
that a live prepared-run route owner exists.

Repository fixture and expected-output posture remains
`internal_validation_summary`. Runtime redaction is not added because these
fixtures are repository-safe validation artifacts, not portable/public/export
artifacts.
