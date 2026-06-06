# Product Adoption Strategy

## Status

Current product adoption strategy.

## Purpose

Describe how users can start adopting Scopecat without replacing working lab
systems up front.

Use this document to answer what first user change Scopecat asks for, what
value that change creates, and what adoption risk must remain visible. Use
[`target-journeys.md`](target-journeys.md) for the canonical journey/use-case
index and [`target-capabilities.md`](target-capabilities.md) for capability
maturity.

## Adoption Principles

- Start with useful review, selection, handoff, and diagnostic value before
  asking users to replace measurement systems.
- Prefer explicit Python or adapter-authored recording over passive scraping
  as the first integration model.
- Keep existing systems responsible for hardware control until a narrower
  workflow proves replacement is worth the risk.
- Make cross-machine value concrete through open-before-import packages,
  preview, and explicit import decisions.
- Treat selective migration as optional and capability-specific, not as a
  project-wide rewrite.
- Keep adoption paths anchored in Measurement Records, review receipts,
  package/export boundaries, and clear authority non-claims.

## Adoption Modes

| Mode | First User Change | User Value | Main Adoption Risk |
| --- | --- | --- | --- |
| Record-first adoption | Keep running measurements in the existing system, then record declared run facts, source references, optional normalized primary data, and review evidence in Scopecat. | Users can find selected measurements, open a durable local record, and attach later parameter, code, setup, artifact, or evidence references. | Users may expect Scopecat to understand raw legacy formats, scientific validity, or execution semantics before those boundaries are owned. |
| Handoff/review-before-import | Select useful measurement data, export a Scopecat-authored package, and let the receiver open it before accepting durable import. | Sharing becomes an explicit package with declared identity, previewable contents, missing-context visibility, and no silent storage mutation. | Package authority and import authority can collapse unless read-only open, preview, and accepted import stay separate. |
| Context-review adoption | Review parameter, setup, code, environment, or reference context without letting Scopecat apply hardware changes or start runs. | Users can inspect point-in-time context, compare variants, and compose run or rerun preparation evidence while existing systems remain authoritative. | Review, compatibility output, live write-back, and hardware apply can look like one workflow unless mutation authority stays explicit. |
| Monitoring/review adoption | Let existing Python-driven measurements emit lifecycle, progress, partial data, and completion events for review. | Users can inspect progress and partial-but-useful data without handing over scheduling, scan-plan, or safety ownership. | Monitoring can be confused with control, automatic retune, or recovery authority. |
| Reference/rerun adoption | Select a known-good or notable reference, compare declared context, and prepare rerun or reproduction evidence while execution remains external. | Changed, missing, unverified, and not-compared facts become visible before reuse. | Objective comparison can be mistaken for setup truth, domain judgment, or rollback authority. |
| Selective legacy replacement | Replace one fragile legacy service, driver, scan boundary, or helper workflow only when a named boundary reduces operational risk. | Users can retire one high-pain path without forcing a project-wide rewrite. | A local replacement can be misread as universal hardware-control framework ownership. |

## Product Posture

Adoption may start from whichever mode solves the strongest local pain, but
design validation should still stay anchored to the canonical journeys,
capabilities, validation evidence, and implementation boundaries.

The near-term product should favor record, review, package, and context
visibility. Execution, hardware apply, runtime readiness, scheduling, and
recovery authority remain opt-in migration targets that need narrower accepted
decisions.

## Update Rule

Update this strategy when a branch changes how users are expected to start
using Scopecat or when a new adoption mode becomes product-relevant.

Do not use this file to track journey ownership, capability maturity,
brownfield current state, transition-state ownership, delivery maturity,
implementation entrypoints, tests, fixtures, or module ownership.
