# Parameter-State Engineering Prototype Promotion Decision

Status: accepted

Date: 2026-06-01

Posture: internal_validation_summary

## Decision

Promote the accepted parameter-state discovery candidates into a route-local
engineering prototype under `scopecat/parameter_state/`.

The prototype owns these local review and storage surfaces:

- adapter-authored parameter-state import preview;
- explicit adapter import review/commit summary;
- reviewed adapter-derived parameter-state storage writer;
- explicit adapter manifest/receipt storage read view;
- source-agnostic adapter/calibration read-view projection;
- parameter-state selection-context summary;
- prepared-run source-agnostic parameter-state consumption;
- prepared-run parameter-state gate, scope alignment, and review-chain
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

Prepared-run consumption must use prior read-view facts. A clean consumption
summary can still produce a review-chain `needs_review` classification when
scope alignment finds partial target coverage; that is a review state, not an
execution permission.

Repository fixture and expected-output posture remains
`internal_validation_summary`. Runtime redaction is not added because these
fixtures are repository-safe validation artifacts, not portable/public/export
artifacts.
