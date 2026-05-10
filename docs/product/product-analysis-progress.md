# Product Analysis Progress

## Status

Initial tracker created for the renamed greenfield project.

## Purpose

Track product-analysis progress, confidence, evidence gaps, and next analysis
sequence before downstream specs or implementation planning start.

This file does not define final product scope. Product promises belong in
`../vision.md`; capability boundaries belong in `../system-map.md` and the
owning subsystem documents.

## Current Situation

Scopecat is a new project workspace intended to carry forward useful product
analysis from the earlier Fricon work while resetting the name, documentation
structure, and architecture framing.

Current high-confidence first adoption pressure:

- ordinary Python measurement scripts should be able to write data
- live inspection should be simple and disposable
- checkpointed writes should remain readable after ordinary interruptions
- measurement and dataset records should reopen by stable IDs
- early adoption should not require managed execution, device control, or old
  history import

Current long-term pressure:

- parameter memory
- scan planning and preview
- code provenance
- instrument leases and runtime state
- managed execution
- workflow composition
- remote validation and execution

## Next Analysis Sequence

1. Migrate the strongest Fricon product-analysis material into Scopecat terms.
2. Challenge the first usable slice against one more concrete migration case.
3. Separate first-slice scope, follow-on backlog, ADR-gated directions, and
   rejected scope.
4. Define success signals and validation tasks.
5. Deepen Measurement History and Scan Framework first.

## Open Questions

- Is Measurement History still the first product wedge after the broader
  platform reframing?
- Which legacy pain point should drive the first technical spike?
- Which concepts need stable names before subsystem specs begin?
- What should remain internal analysis versus future public documentation?
