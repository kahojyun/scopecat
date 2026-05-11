# Fricon Legacy Docs Input

## Status

Raw

## Source

Snapshot copied from the local Fricon predecessor workspace on 2026-05-11. The
imported files are under `source/`.

The predecessor root `AGENTS.md` was renamed to `root-AGENTS.imported.md` in
the copied source tree so future tooling does not treat it as active
instructions for this repository.

Fricon is the predecessor project to this project. Its docs are retained here
because the measurement-history product analysis and long-term product goals
remain useful evidence, even though the Fricon analysis stopped partway through
when the work moved into this broader project model.

## Summary

The Fricon docs capture a predecessor product thesis for a local measurement
data system. They focus on replacing the fragile Data Vault/Grapher loop for
new interactive measurements, then extending toward a local experiment memory
and reviewed action layer.

The most valuable material is:

- initial measurement-history adoption analysis around write, inspect,
  interruption-safe reopen, and stable ID workflows;
- measurement and dataset shape pressure from VNA S21 traces, IQ/readout data,
  optimizer/minimizer records, ragged data, and complex values;
- product boundaries for keeping legacy runners, notebooks, parameter files,
  and setup context as bridges instead of first-class owned truth;
- long-term goals around parameters, managed code provenance, run manifests,
  calibration evidence, setup/device state, reviewed replay, and reviewable
  automation;
- lessons from product-analysis cleanup, documentation governance, and
  predecessor reset decisions.

The content should be treated as predecessor evidence, not as current product
direction. In particular, Fricon analyzed measurement history as the central
entry point. This project should re-evaluate those claims under a more complete
capability system where measurement history, scan structure, parameter memory,
code assets, instrument runtime, managed runner, orchestration, and remote
execution can be analyzed on more equal terms.

## Extracted To

- `../../research-index.md` records this import as raw predecessor evidence.
- `../../../document-index.md` lists this import as a research entry point.
- No product, journey, capability, domain, architecture, or decision document
  has accepted Fricon claims yet.

## Remaining Value

Use this import to extract durable evidence into current project docs. High
value extraction targets include:

- journey and pain evidence for the measurement-history adoption slice;
- capability pressure that should survive the move from Fricon to the broader
  project model;
- stable domain vocabulary around measurements, datasets, traces, parameters,
  provenance, calibration, and reviewed actions;
- long-term architecture constraints that early models should not foreclose;
- explicit rejected or ADR-gated scope inherited from Fricon.

Future extraction should preserve the provenance that Fricon was replaced by
this project and should avoid treating any Fricon scope order as accepted for
the current system.

## Source Inventory

Root files:

- [`source/README.md`](source/README.md)
- [`source/root-AGENTS.imported.md`](source/root-AGENTS.imported.md)

Product docs:

- [`source/docs/product/vision.md`](source/docs/product/vision.md)
- [`source/docs/product/personas.md`](source/docs/product/personas.md)
- [`source/docs/product/story-map.md`](source/docs/product/story-map.md)
- [`source/docs/product/capability-map.md`](source/docs/product/capability-map.md)
- [`source/docs/product/product-analysis-progress.md`](source/docs/product/product-analysis-progress.md)
- [`source/docs/product/future-concepts.md`](source/docs/product/future-concepts.md)
- [`source/docs/product/python-sdk-ux.md`](source/docs/product/python-sdk-ux.md)
- [`source/docs/product/glossary.md`](source/docs/product/glossary.md)

Research docs:

- [`source/docs/research/README.md`](source/docs/research/README.md)
- [`source/docs/research/lessons-for-fricon.md`](source/docs/research/lessons-for-fricon.md)
- [`source/docs/research/legacy-measurement-sample-lessons.md`](source/docs/research/legacy-measurement-sample-lessons.md)
- [`source/docs/research/strategic-follow-on-future-systems.md`](source/docs/research/strategic-follow-on-future-systems.md)

Architecture, domain, and decision docs:

- [`source/docs/architecture/README.md`](source/docs/architecture/README.md)
- [`source/docs/architecture/compatibility-policy.md`](source/docs/architecture/compatibility-policy.md)
- [`source/docs/domain/README.md`](source/docs/domain/README.md)
- [`source/docs/decisions/ADR-000-template.md`](source/docs/decisions/ADR-000-template.md)
- [`source/docs/decisions/ADR-001-v02-clean-reset-boundary.md`](source/docs/decisions/ADR-001-v02-clean-reset-boundary.md)
- [`source/docs/decisions/ADR-002-documentation-governance.md`](source/docs/decisions/ADR-002-documentation-governance.md)

AI, user, spec, implementation, and postmortem docs:

- [`source/docs/README.md`](source/docs/README.md)
- [`source/docs/ai/project-context.md`](source/docs/ai/project-context.md)
- [`source/docs/ai/agent-steering.md`](source/docs/ai/agent-steering.md)
- [`source/docs/ai/documentation-update-policy.md`](source/docs/ai/documentation-update-policy.md)
- [`source/docs/user/documentation-plan.md`](source/docs/user/documentation-plan.md)
- [`source/docs/specs/README.md`](source/docs/specs/README.md)
- [`source/docs/implementation-plans/README.md`](source/docs/implementation-plans/README.md)
- [`source/docs/postmortems/v0-lessons.md`](source/docs/postmortems/v0-lessons.md)
