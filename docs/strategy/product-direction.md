# Product Direction

## Status

Current product direction.

## Purpose

State what Scopecat is trying to become and the default ownership assumptions
that guide discovery. Narrower validation, decision, contract, and architecture
docs should own details when they are needed.

## Direction

Scopecat is a progressively adoptable evidence and handoff layer for scientific
measurement workflows.

It should help users make experiment code, data, parameters, analysis choices,
and handoff bundles easier to explain, select, package, compare, and review
around existing lab systems.

Early value should come from practical workflow return: recovery, selection,
handoff, diagnostic clarity, readable progress, or bounded automation evidence.
Provenance and auditability matter when they support those workflows.

## Ownership Assumptions

Existing experiment systems own execution and mutation by default: instrument
communication, hardware state, acquisition timing, live parameter application,
trusted scan execution, and emergency recovery.

Scopecat can own records and explanations around those systems: measurement
records, context, lifecycle events, code references, parameter snapshots,
generated artifacts, selected references, analysis choices, quality evidence,
annotations, and handoff packages.

Cross-machine value should start from portable records, explicit export/import,
handoff packages, and optional shared-storage references. This makes Scopecat
record-aware across machines, not a distributed experiment-control system.

Recording should be explicit. Experiment code, helper libraries, or lab-owned
bridges should deliberately send data, sweep semantics, lifecycle/status
events, parameters, code/context references, progress markers, and saved
decisions into Scopecat.

## Integration Boundary

Local conventions, domain-specific formats, free-text redaction policy,
physical setup semantics, and framework-specific bridge behavior should enter
through explicit adapter or policy surfaces. They should not silently become
core product scope because one workflow needed them.

## Non-Goal Groups

These are not default adoption prerequisites:

- replacing existing measurement GUIs, control GUIs, drivers, or hardware
  control frameworks;
- replacing LabRAD, QCoDeS, Labber, Bluesky, vendor systems, or lab-owned
  scripts;
- passively scraping arbitrary measurement artifacts as the main integration
  model;
- providing a complete reader/export/conversion suite or semantic parser for
  arbitrary user artifacts;
- owning calibration write-back, parameter mutation, scheduling, remote
  execution, central storage, or sync services;
- becoming the authoritative source of hardware, setup, sample, or topology
  truth;
- replacing lab operations, ELN, LIMS, publication, or report-generation
  systems;
- defining a universal parameter, setup, sample, or topology ontology.

