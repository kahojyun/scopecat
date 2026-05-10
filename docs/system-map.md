# System Map

## Status

Draft capability map. Boundaries are architectural hypotheses until validated
against product analysis, interviews, and technical spikes.

## Foundational Capabilities

### Measurement History

Records what happened: experiment runs, datasets, derived datasets, imported
legacy datasets, scan-point records, run metadata, dataset lineage, and links
to optional provenance references.

Initial maturity target: deep.

### Scan Framework

Structures scan semantics: scan plans, variables, fixed parameters,
scan-point expansion, desired-state rendering, preview, diffing, and scan
metadata.

Initial maturity target: deep for early scan migration, medium-deep for remote
execution contracts.

### Parameter Memory

Records durable parameter knowledge: parameter schemas, slots, sets,
immutable snapshots, calibration state, update proposals, and history.

Initial maturity target: medium.

### Code Asset Registry

Manages code identity: scripts, analysis routines, fitting code, calibration
code, drivers, service modules, templates, source references, versions,
content hashes, entrypoints, and compatibility metadata.

Initial maturity target: shallow to medium.

### Instrument Runtime

Manages live resources: instrument registry, service lifecycle, health,
resource leases, conflict prevention, desired-state application, and actual
state snapshots.

Initial maturity target: medium.

### Managed Code Runner

Executes code in a controlled and observable way: execution plans, records,
environment snapshots, stdout/stderr, artifacts, supervision, cancellation,
and status.

Initial maturity target: shallow to medium.

## Composition Capabilities

### Workflow / Orchestration Layer

Coordinates multi-step protocols such as coarse scan, fit, fine scan,
calibration proposal, human approval, and retry policy.

Initial maturity target: draft.

### Remote Execution Coordinator

Receives frozen experiment packages from local clients, validates them, starts
remote execution, streams monitoring data, supports cancellation, and finalizes
records.

Initial maturity target: draft.

## Maturity Matrix

| Capability | Product | Domain | Architecture | Spec |
| --- | --- | --- | --- | --- |
| Measurement History | Deep | Deep | Deep | Deep |
| Scan Framework | Deep | Deep | Medium-Deep | Medium-Deep |
| Parameter Memory | Medium-Deep | Deep | Medium | Medium |
| Instrument Runtime | Medium | Medium | Medium | Shallow-Medium |
| Code Asset Registry | Medium | Medium | Shallow-Medium | Shallow |
| Managed Code Runner | Medium | Medium | Shallow-Medium | Shallow |
| Workflow Layer | Draft | Draft | Shallow | Shallow |
| Remote Execution Coordinator | Draft | Draft | Shallow | Shallow |
