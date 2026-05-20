# Shared Model Extraction Deferral

## Status

Discovery deferral, not an ADR.

This note records a negative decision for the current discovery stage: do not
extract shared domain models or shared implementation modules from the current
slice-local candidates yet.

## Decision

Keep the current implementation candidates slice-local.

Do not introduce a shared `core`, `domain`, `models`, record schema, relation
schema, warning taxonomy, preview-metadata schema, workflow model, or reusable
builder package from the current discovery work.

This defers shared architecture. It does not reject the recurring concepts.

## Context

The cross-slice synthesis shows repeated vocabulary across selected measurement
export, running measurement inspection, calibration work continuation, and
measurement/data-shape fixtures:

- measurement record;
- source identity;
- primary data reference;
- declared preview metadata;
- linked context;
- lifecycle or progress state;
- intervention or operation;
- proposal;
- warning or attention state;
- authority and provenance.

Those concepts are real discovery pressure. They are useful for analysis,
fixture design, validation wording, and future architecture discussions.

They are not yet stable enough to become shared product schema or shared code.
The slices still differ in their immediate user jobs:

- export needs selected membership, bundle/include state, provenance, and
  preview readiness;
- running inspection needs progress, completeness, freshness, and partial
  recorded data visibility;
- calibration continuation needs review gates, blocked steps, proposed writes,
  and available interventions.

The overlap is conceptual before it is architectural.

## Rationale

Premature shared extraction would create several risks:

- it could turn fixture vocabulary into durable product schema before the
  product boundary is earned;
- it could make one slice's local tradeoffs look like general architecture;
- it could hide different meanings behind shared names such as `record`,
  `artifact`, `warning`, `operation`, or `state`;
- it could pull final storage identity, relation graph, GUI, executor, package,
  importer, plotting, or write-back decisions into code indirectly.

The current slice-local builders are intentionally narrow. They make each
validation result executable without claiming a final architecture.

## Extraction Triggers

Shared model extraction becomes worth reconsidering only when a concrete next
implementation task would otherwise duplicate validated behavior across at
least two slices.

Useful triggers include:

- two or more implementation candidates need the same reference-validation
  behavior, with matching failure semantics and tests;
- export and running inspection both need the same declared preview metadata
  structure in production-shaped code;
- linked context include states need to be consumed by more than one slice with
  the same user-visible meaning;
- warning or attention states need shared ordering, severity, suppression, or
  display semantics across multiple product surfaces;
- proposal records become a concrete implementation input for both parameter
  history and calibration continuation.

Before extraction, the repeated behavior should have:

- at least two validated slices using it for the same user-facing question;
- explicit tests that would otherwise be duplicated;
- documented boundaries for what the shared model does not decide;
- a narrower accepted decision or ADR naming the ownership and scope.

## Still Separate

This deferral keeps these decisions separate:

- final measurement, artifact, attachment, relation, and data-shape schema;
- final storage identity, object ID, external-reference, and package path
  model;
- checksum, archive, importer, and package integrity contract;
- export/import GUI, live monitor GUI, and calibration resume GUI;
- plotting dependency, rendered preview, and interactive slicing API;
- automatic schema inference from legacy files or notebooks;
- recursive relation traversal and analysis-DAG inference;
- local executor, scheduler, retry policy, resource arbitration, and hardware
  control;
- Scopecat-decided parameter mutation, write-back, rollback, and calibration
  authority.

## Consequences

New discovery or implementation slices should continue to use fixture-local or
slice-local vocabulary unless a narrower decision accepts shared terms.

When wording overlaps, documents should say whether a term is:

- a candidate concept used for comparison;
- a fixture field;
- an implementation-candidate input or output;
- an accepted product contract.

Existing implementation candidates under `implementation_candidates/` remain
experimental and slice-local. If a future shared module is accepted, the older
spikes and candidates should be reviewed then: either retire them as historical
validation artifacts or keep them as regression examples for the accepted
boundary.
