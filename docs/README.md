# Scopecat Docs

## Status

Active greenfield documentation workspace.

## Purpose

`docs/` is the single home for product analysis, system architecture,
subsystem boundaries, integration contracts, decisions, research notes, and
AI-agent guidance while Scopecat is being designed.

Scopecat starts from a concrete first adoption loop:

```text
write from ordinary Python
  -> inspect simple live data
  -> keep checkpointed writes readable
  -> reopen by stable ID for analysis
```

The larger ambition is a progressively adoptable experimental automation
platform. Early documents should keep this ambition visible without forcing a
big-bang migration or pretending every subsystem is implementation-ready.

## Design Stance

Scopecat should be designed as independently useful foundational capabilities
that can later compose into higher-level automation:

1. Measurement History
2. Scan Framework
3. Parameter Memory
4. Code Asset Registry
5. Instrument Runtime
6. Managed Code Runner

Composition capabilities such as workflow orchestration and remote execution
should compose the foundational systems rather than absorb their domain models.

## Reading Order

1. `vision.md`
2. `system-map.md`
3. `product/product-analysis-progress.md`
4. `integration/data-ownership.md`
5. `integration/dependency-rules.md`
6. `subsystems/measurement-history/README.md`
7. `subsystems/scan-framework/README.md`
8. Other subsystem READMEs as their design depth increases

## Target Directory Structure

This is the intended documentation structure. Some directories may remain
sentinel-only until there is enough validated product or architecture input.

```text
docs/
  README.md
  vision.md
  system-map.md
  glossary.md

  product/
    product-analysis-progress.md

  integration/
    README.md
    composition-model.md
    data-ownership.md
    dependency-rules.md
    domain-boundaries.md
    cross-system-contracts.md
    release-staging.md

  remote-execution/
    README.md
    local-authoring-remote-execution.md
    experiment-package.md
    remote-validation.md
    submission-lifecycle.md
    monitoring-and-cancellation.md
    security-and-permissions.md

  workflows/
    README.md
    calibration-loop.md
    adaptive-scan-workflow.md
    batch-analysis-workflow.md

  subsystems/
    README.md
    measurement-history/
      README.md
      product/
        product-brief.md
        standalone-adoption.md
        user-stories.md
        non-goals.md
      domain/
        README.md
      architecture/
        README.md
      specs/
      decisions/
    scan-framework/
    parameter-memory/
    code-asset-registry/
    instrument-runtime/
    managed-code-runner/

  decisions/
  research/
  ai/
  user/
```

## Source-Of-Truth Ownership

- `vision.md` owns the durable product thesis and ambition.
- `system-map.md` owns the current capability map and maturity posture.
- `product/product-analysis-progress.md` owns analysis status, evidence gaps,
  validation sequence, and open product questions.
- `integration/` owns cross-subsystem contracts, ownership rules, dependency
  direction, and release staging.
- `remote-execution/` owns local-authoring and remote-execution contracts.
- `workflows/` owns multi-step procedure sketches that compose subsystems.
- `subsystems/<name>/` owns product, domain, architecture, specs, and decisions
  for that subsystem.
- `decisions/` owns project-wide ADRs. Subsystem-specific ADRs live under the
  owning subsystem.
- `research/` owns external references and interview-to-architecture mapping.
- `ai/` owns agent routing and documentation update policy, not product truth.
- `user/` is reserved for future public documentation planning.

## Editing Rules

- Keep early files short and explicit about confidence.
- Mark hypotheses, accepted decisions, and open questions separately.
- Do not promote future subsystem ideas into first-slice requirements.
- Do not use `specs/` to define product scope before upstream product and
  architecture documents have stabilized.
- Prefer one owner per concept. Cross-links are references, not duplicate
  ownership.
- Public-facing docs require redaction review before publication.
