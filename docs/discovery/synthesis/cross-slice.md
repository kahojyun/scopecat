# Cross-Slice Discovery Synthesis

## Status

Compact historical discovery synthesis, not an ADR.

This document keeps the useful residue from earlier cross-slice discovery after
the detailed slice corpus was removed from active docs. It is evidence
orientation only. It does not accept a final schema, storage model, workflow
model, GUI contract, export package format, executor design, relation graph,
or warning taxonomy.

For current modeling and architecture work, start from:

| Owner | Use For |
| --- | --- |
| [`../../architecture/domain-model.md`](../../architecture/domain-model.md) | Current initial domain concepts and maturity labels. |
| [`../../architecture/context-map.md`](../../architecture/context-map.md) | Context ownership, anti-corruption boundaries, and integration relationships. |
| [`../../architecture/transition-architecture.md`](../../architecture/transition-architecture.md) | Brownfield entrypoint-driven transition architecture. |
| [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md) | Current workflow validation state and missing seams. |
| [`../archive/slice-inventory.md`](../archive/slice-inventory.md) | Compact historical index of removed discovery slice bodies. |
| [`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md) | Current deferral rule for shared domain model extraction. |

## Carry Forward

The old cross-slice corpus is still useful for a small set of recurring design
pressures:

- measurement records are the strongest current anchor for recorded experiment
  data, selected export/import, handoff, inspection, and traceability;
- adapters and anti-corruption boundaries separate legacy source references,
  adapter-normalized primary data, source observation, and Scopecat-owned
  durable storage;
- context such as parameter state, setup binding, experiment code,
  environment facts, selected references, and supporting evidence should remain
  family-owned until repeated accepted workflows need the same stable contract;
- review findings are local visibility by default, not approval gates,
  hardware safety decisions, measurement invalidation, or execution authority;
- packages, reports, review summaries, fixtures, and local receipts are
  different artifact boundaries and must not inherit each other's redaction or
  portability rules.

## Stable Separations

Keep these separations visible when evaluating future implementation work:

- Selected records are explicit. Adjacent IDs, rejected alternatives, linked
  artifacts, source runs, or relation graphs are not automatically included.
- Declared metadata is the first supported path for preview. Inference from
  notebooks, filenames, weak headers, sidecars, or legacy readers remains
  optional future help, not the trust base.
- Source identity, external local paths, package-relative materialized files,
  fixture paths, and future managed storage identities are distinct.
- External legacy references can preserve provenance without implying
  Scopecat can parse, preview, plot, repair, or own the external system.
- Supporting evidence is not canonical context by default. Opaque files,
  notes, logs, screenshots, debug objects, and attachments stay supporting
  evidence unless a later accepted boundary promotes a specific family.
- Proposed writes and applied writes are separate. Recording a user-authored
  proposal does not imply Scopecat-decided mutation or write-back authority.
- Partial running data can be visible as normal state. Incompleteness is a
  warning only when it blocks a declared review need.
- Setup binding, parameter state, station/device registry facts, experiment
  code context, and declared environment facts are related context families,
  not one shared state model.
- Selected references are explicit user-chosen anchors. Objective comparison
  findings do not become cause attribution or user interpretation.
- Experiment code context does not imply Git semantics, environment
  restoration, runnable readiness, import, loading, or execution.
- Environment operation review can record approved local operations and typed
  results without becoming a general package manager, runtime readiness, or
  managed runner abstraction.

## Do Not Rebuild

Do not recreate the removed slice-era synthesis tables as active docs. New
validation should start from a brownfield entrypoint, architecture transition
gap, target journey gap, workflow/use-case validation question, or clearly
scoped technical risk.

When a recurring concept appears in multiple places, first decide whether it
is only vocabulary, a route-local object, a process/integration object, an
artifact descriptor, or a candidate shared domain concept. Promote it only
through the current architecture, decision, product, and engineering owner
documents.
