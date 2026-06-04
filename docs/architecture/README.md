# Architecture

## Status

Initial architecture model for brownfield-guided design.

## Purpose

Architecture docs translate brownfield current-state evidence into a small
domain model, context map, and transition design frame. Use these docs before
promoting discovery slices, extracting shared models, or cleaning historical
discovery material.

These docs are not public user documentation, final storage schema, stable
Python SDK, complete target architecture, or implementation task list.

## Documents

| Document | Use For |
| --- | --- |
| [`as-is-architecture.md`](as-is-architecture.md) | Current lab-system architecture as integration pressure for Scopecat. |
| [`domain-model.md`](domain-model.md) | Candidate domain concepts, maturity labels, and concept boundaries. |
| [`context-map.md`](context-map.md) | Bounded contexts, ownership posture, and anti-corruption relationships. |
| [`transition-architecture.md`](transition-architecture.md) | Brownfield entrypoint-driven transition architecture and slice-classification frame. |
| [`artifact-boundary-and-redaction.md`](artifact-boundary-and-redaction.md) | Artifact surfaces, repository-safe fixtures, local review surfaces, and portable/public/export redaction boundaries. |
| [`measurement-data-reference-boundary.md`](measurement-data-reference-boundary.md) | Boundary between normalized primary data, external source references, attachments, and previewable data items. |
| [`package-purpose-boundary.md`](package-purpose-boundary.md) | Boundary between analysis/review packages, shared lab references, and future offline execution migration. |
| [`artifact-preview-boundary.md`](artifact-preview-boundary.md) | Boundary between arbitrary artifacts and declared previewable data items. |
| [`complex-response-boundary.md`](complex-response-boundary.md) | Complex-valued response metadata posture for previewable data items. |
| [`external-file-reference.md`](external-file-reference.md) | External file reference vocabulary, observed-file state, and non-backup posture. |

## Reading Rules

Read these docs after brownfield current-state material and before engineering
workflow validation when deciding what a slice means architecturally.

Use architecture docs to answer:

- which brownfield entrypoint a concept supports;
- whether a concept is core, supporting, or historical;
- which context owns a behavior;
- whether a slice should influence current architecture, remain evidence, or
  be removed from active docs.

Do not use these docs to claim final public contracts. Use decision records
when a candidate concept becomes an accepted architecture decision.
