# Fricon Legacy Docs Input

## Status

Extracting

## Source

Snapshot copied from the local Fricon predecessor workspace on 2026-05-11. The
retained high-signal files are under `source/`.

Low-value predecessor scaffolding, templates, routing docs, and imported agent
instructions were pruned after W1 because current Scopecat policy and the W1
inventory supersede them. Git history is sufficient if those deleted process
files are needed again.

Fricon is the predecessor project to this project. Its docs are retained here
because the measurement-history product analysis and long-term product goals
remain useful evidence, even though the Fricon analysis stopped partway through
when the work moved into this broader project model.

Any status labels inside retained source files are Fricon-local historical
statuses. They do not imply current Scopecat acceptance. Current acceptance is
owned only by Scopecat wrappers, indexes, extracted notes, promoted durable
docs, or explicit decisions.

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
- lessons from product-analysis cleanup and predecessor reset decisions.

The content should be treated as predecessor evidence, not as current product
direction. In particular, Fricon analyzed measurement history as the central
entry point. This project should re-evaluate those claims under a more complete
capability system where measurement history, scan structure, parameter memory,
code assets, instrument runtime, managed runner, orchestration, and remote
execution can be analyzed on more equal terms.

## Current Use

- [`../../extracted/research-acceptance-readiness-triage.md`](../../extracted/research-acceptance-readiness-triage.md)
  classifies Fricon predecessor content by acceptance readiness for Scopecat.
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

Cleanup note: after W1, this snapshot keeps only predecessor evidence, pressure,
and rejection-rationale documents that may still support W2 fixture selection
or later ADR/capability extraction. It no longer keeps predecessor docs
scaffolding as an active reading path.

## Source Inventory

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

- [`source/docs/research/lessons-for-fricon.md`](source/docs/research/lessons-for-fricon.md)
- [`source/docs/research/legacy-measurement-sample-lessons.md`](source/docs/research/legacy-measurement-sample-lessons.md)
- [`source/docs/research/strategic-follow-on-future-systems.md`](source/docs/research/strategic-follow-on-future-systems.md)

Architecture, decision, and postmortem docs:

- [`source/docs/architecture/README.md`](source/docs/architecture/README.md)
- [`source/docs/architecture/compatibility-policy.md`](source/docs/architecture/compatibility-policy.md)
- [`source/docs/decisions/ADR-001-v02-clean-reset-boundary.md`](source/docs/decisions/ADR-001-v02-clean-reset-boundary.md)
- [`source/docs/postmortems/v0-lessons.md`](source/docs/postmortems/v0-lessons.md)
