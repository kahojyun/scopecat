# Supporting Evidence Reference Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated supporting-evidence reference candidate into a
route-local engineering prototype under `scopecat.measurement_context`.

The promoted surface is intentionally narrow:

- summarize explicitly supplied debug, audit, handoff, or review-evidence
  references;
- distinguish `attachment`, `artifact`, and `unspecified` as label-only
  evidence kinds;
- require explicit lifecycle posture so pre-run, during-run, post-run, and
  handoff evidence do not blur together;
- relate evidence to measurement, running-measurement, prepared-run,
  operator-approval, parameter-state, or calibration-step targets;
- surface unavailable evidence or target references as review findings.

The accepted chain is:

```text
explicit supporting-evidence manifest
  -> one user-supplied evidence reference
  -> declared related targets
  -> local supporting-evidence review summary
```

This promotion keeps supporting evidence reference-only and side-effect-free.
It does not import payloads, observe files, parse evidence, validate
checksums, mutate storage, claim external file authority, generate previews,
validate artifact provenance, recursively traverse relations, decide
measurement validity, define GUI behavior, or define a shared attachment
schema.

## Boundary

The promoted output is local review data. It is not a portable/public/export
artifact.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surface does not
produce portable handoff, package, or public documentation artifacts. The live
implementation validates public-safe managed identifiers and rejects policy
expansion, unsupported evidence kinds, unsupported lifecycle stages,
unsupported target relations, non-relative declared paths, payload/provenance
passthrough, duplicate target links, and missing reason fields for unavailable
or redacted references.

## Rationale

Measurement records and review workflows need a place to point at user-supplied
diagnostic or audit evidence without treating it as primary data, canonical
context, or artifact provenance. Promoting this narrow reference surface gives
later post-run review and running-record review slices a stable local input
without accepting payload reads, attachment storage, provenance validation, or
GUI workflow.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Supporting evidence reference | Promoted into route-local engineering code with typed request/result objects and a raw-dictionary adapter only at the fixture/current-caller edge. | [`scopecat/measurement_context/README.md`](../../../scopecat/measurement_context/README.md), this decision |
| Supporting artifact provenance and observation | Remain candidate-only; `artifact` is only a label at this boundary. | [`../../discovery/synthesis/measurement-context-backlog.md`](../../discovery/synthesis/measurement-context-backlog.md) |
| Post-run review bundles | Remain candidate-only consumers of declared context-link and supporting-evidence summaries. | [`../../discovery/synthesis/measurement-context-backlog.md`](../../discovery/synthesis/measurement-context-backlog.md) |

## Next Decision Gate

Do not continue by promoting a general attachment subsystem. Future work should
choose one explicit authority change:

- supporting artifact provenance;
- supporting artifact file observation;
- running-record supporting evidence update;
- post-run review bundle composition;
- storage/package materialization of supporting evidence;
- GUI or notebook presentation.

Each path needs its own non-claims before it can add payload reads, file
observation, checksum validation, storage mutation, artifact provenance,
preview generation, package/export behavior, measurement-validity decisions,
or shared schemas.
