# Architecture

## Status

Initial architecture model for brownfield-guided design.

## Purpose

Architecture docs translate brownfield current-state evidence into a small
domain vocabulary and context map. Use these docs before promoting discovery
evidence, extracting shared models, or changing accepted architecture
boundaries.

These docs are not public user documentation, final storage schema, stable
Python SDK, complete target architecture, or implementation task list.

## Documents

| Document | Use For |
| --- | --- |
| [`as-is-architecture.md`](as-is-architecture.md) | Current lab-system architecture as integration pressure for Scopecat. |
| [`domain-model.md`](domain-model.md) | Layered domain vocabulary, concept boundaries, and modeling rules. |
| [`context-map.md`](context-map.md) | Bounded contexts, ownership posture, and anti-corruption relationships. |
| [`artifact-boundary-and-redaction.md`](artifact-boundary-and-redaction.md) | Artifact surfaces, repository-safe fixtures, local review surfaces, and portable/public/export redaction boundaries. |

## Reading Rules

Read these docs after brownfield current-state material and before engineering
workflow validation when deciding what evidence means architecturally.

Use architecture docs to answer:

- which brownfield entrypoint a concept supports;
- which domain vocabulary layer a concept belongs to;
- which context owns a behavior;
- whether historical evidence should influence current architecture or remain
  archived evidence.

Do not use these docs to claim final public contracts. Use ADRs when a
candidate concept becomes an accepted architecture decision.
