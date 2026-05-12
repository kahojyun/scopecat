# Document Index

## Purpose

Compact index of high-value docs for readers and future AI sessions. This file
is allowed to change as the documentation set changes; stable documentation
policy belongs in `README.md`.

If this index and a document's own status disagree, trust the document's own
status.

## Index

| Document | Status | Use For | Caveat |
| --- | --- | --- | --- |
| `README.md` | Stable policy | Documentation purpose, entry points, and editing rules. | Should stay compact and avoid current file inventory. |
| `AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/`. | Keep operational; do not move long background here. |
| `progressive-adoption-progress-tracker.md` | Active tracker | Tracking journey-first discovery, adoption ladders, migration wedges, contracts, and decision promotion. | `JC-001` now has an accepted passive evidence-view decision; broader subsystem ideas remain hypotheses until promoted by later decisions. |
| `evidence-and-pain-point-inventory.md` | Ready as W1 evidence input for W2 journey drafting | W1 owner for evidence, lab/user context, top-level pain narratives, pain/pressure rows, adoption blockers, external-framework baselines, statement-kind separation, and first-fixture source-map requirements. Use it with the `JC-001` selection note when drafting the first W2 journey. | Start from its W2 quick start and source-map guidance. `PN` rows are mixed statement kinds; role-play and behavioral priors are prompt inputs, not user research; external refs are illustrative baselines; physical setup records are declared or externally evidenced state; pain rank is not a roadmap; internal diagnostics should preserve useful context, while public docs and external/support-boundary exports require sanitization or redaction. |
| `jc-001-journey-selection-note.md` | Ready for first W2 journey drafting | Selected W2 candidate, public-safe synthetic fixture boundary, acceptance pressure mapping, JTBD conversion, and current/future journey seeds for `JC-001`. | This is not the journey document, capability map, architecture contract, or implementation scope. It intentionally keeps the fixture as offline explanation and ambiguity review; no execution, hardware control, write-back, rollback, environment mutation, or framework replacement is accepted. |
| `jc-001-work-bundle-explanation-journey.md` | Ready | First W2 journey: current-state and future-state offline explanation of an existing work bundle with selected context, code-shape evidence, generated/copied sidecars, variants, ambiguity, sharing boundaries, and producer-side write obligations implied by read needs. | It does not accept execution, hardware control, write-back, rollback, environment mutation, known-good comparison, or scientific-equivalence scoring. |
| `jc-001-capability-adoption-extraction.md` | Ready for W4 migration-wedge shaping | Journey-scoped W3 extraction of touched capabilities, smallest standalone adoption steps, minimum producer facts, capability ordering, and the first wedge candidate. | This is not a full capability map, architecture contract, subsystem spec, or implementation plan. Keep future wedge scope tied to offline bundle explanation. |
| `jc-001-existing-bundle-to-explainable-context-wedge.md` | Ready for concept/contract extraction | First W4 migration wedge: existing work bundle to explainable context bundle, including scope, non-goals, involved capability pressure, producer facts, evidence-view requirements, validation checks, and spike boundary. | This is not implementation architecture or a technical spike. It keeps the first slice offline, read-only, no-mutation, and no-execution. |
| `jc-001-concepts-and-contracts.md` | Ready; spike validated and decision promoted | Minimum domain concepts, provisional cross-capability contracts, evidence-view contract, and spike boundary for the first wedge. | This is not a full domain model, storage schema, API design, subsystem spec, or ADR. The completed spike validates only static evidence-view generation from the synthetic fixture, now promoted by the passive evidence-view decision. |
| `jc-001-static-analysis-spike.md` | Ready; promoted by accepted decision | Result of the narrow technical spike: a static analyzer can generate the JC-001 evidence view from the synthetic fixture while preserving roles, relations, conflicts, missing facts, sharing boundaries, and no-execution/no-mutation limits. | This validates only the passive explanation boundary. It does not validate arbitrary legacy parsing, notebook handling, binary handling, storage, UI, source-of-record authority, hardware truth, execution, or support-boundary export policy. |
| `jc-001-passive-evidence-view-decision.md` | Accepted | Accepted decision for the first JC-001 product wedge: read-only static evidence-view generation from an existing work bundle, with deferred write, execution, hardware, parser, storage, UI, and export-policy boundaries. | This does not promote full subsystem ownership or a general importer. Capability names remain provisional pressure labels until a capability map promotes ownership boundaries. |
| `jc-001-passive-evidence-view-prototype-scope.md` | Ready for implementation spike | Implementation-facing scope for the accepted passive evidence-view prototype: expected inputs, JSON/Markdown outputs, minimal implementation shape, acceptance checks, non-goals, risks, and selected committed public-safe test-fixture strategy. | This is not implementation architecture. It keeps the first prototype read-only and fixture-sized; the selected fixture strategy is test-owned and does not accept broader fixture import or sample-data policy. |
| `research/README.md` | Stable policy | Research directory purpose and promotion rule. | Does not define product direction. |
| `research/AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/research/`. | Keeps raw research from being treated as product truth. |
| `research/research-index.md` | Working index | Current research inputs, extraction state, and caveats. | Research entries are evidence inputs unless separately promoted. |
| `research/extracted/research-acceptance-readiness-triage.md` | Transitional | Preferred entry point for deciding which raw research claims are accepted guardrails, evidence, inferences, hypotheses, future pressure, ADR-gated items, or rejected first-slice directions. | Keep through W2 validation, then delete or archive after useful claims move into narrower owner docs. |
| `research/extracted/legacy-experiment-code-sample-validation.md` | Transitional | Validation of the raw research triage against two copied legacy experiment code trees; use for concrete evidence on companion artifacts, settings drift, analysis handoff, hardware bring-up, dependency pain, notebook hygiene, and portability pressure. | Keep through W2 validation, then delete or archive after validation cases move into journey fixtures, capability/adoption hypotheses, architecture questions, or ADR triggers. |
| `research/greenfield-experimental-automation-architecture-notes.md` | Quarantined | Automation architecture pressure, historical vocabulary, candidate boundaries, and questions. | Preserve capability pressure beyond Measurement History, but do not use as a product plan, implementation order, or subsystem scaffold. |
| `research/raw/fricon-legacy-docs/README.md` | Extracting research input | Predecessor project documentation snapshot, especially measurement-history analysis and long-term experiment-memory goals. | Scopecat replaces the predecessor direction; use the extracted triage first. After W1, return to raw predecessor material only for exact examples, citations, or W2 fixtures. |

## Possible Future Areas

This is a reference taxonomy, not a scaffold to create in advance. Add these
areas only when there is durable content with a clear owner and purpose.

```text
docs/
  user/          # Public, redacted MkDocs-facing documentation.
  project/       # Vision, glossary, roadmap, and project context.
  product/       # Personas, evidence, pain points, opportunity maps.
  journeys/      # End-to-end user journeys that cross capabilities.
  architecture/  # System map, ownership, dependencies, contracts.
  capabilities/  # Capability-level adoption, domain, and architecture notes.
  concepts/      # Stable cross-capability domain concept cards.
  decisions/     # Project-wide ADRs.
  research/      # Raw or semi-processed research inputs.
```

## Maintenance

Update this index when a document becomes a regular entry point for future
work, when its status changes meaningfully, or when a risky caveat needs to be
visible before reading.
