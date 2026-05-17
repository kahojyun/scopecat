# Product Brief

## Status

Drafting product direction and boundaries.

## Purpose

State the current product direction, default boundaries, and non-goals. Detailed
validation plans, API contracts, storage models, UI specs, and ADRs should live
in narrower owner documents when they are needed.

## Product Direction

Scopecat is a progressively adoptable evidence and handoff layer for scientific
measurement workflows.

It helps users make experiment code, data, parameters, analysis choices, and
handoff bundles easier to explain, select, package, compare, and review around
existing lab systems.

Early value should come from practical workflow return: recovery, selection,
handoff, diagnostic clarity, readable progress, or bounded automation evidence.
Provenance and auditability matter, but they should emerge from useful
workflow records rather than require separate clerical work.

## Adoption Model

Scopecat should be adopted through narrow paths that are useful on their own.
Before a path is promoted, it should name:

- the user behavior it changes;
- the minimum information users or lab code must provide;
- the output users can judge;
- what Scopecat does not touch;
- how the path can fail or be disabled safely.

Different users may start from different paths. A later complete workflow may
compose several paths, but first adoption should not require replacing a lab's
working acquisition stack.

## Default Boundary

Existing experiment systems own execution and mutation by default:

- instrument communication and driver behavior;
- hardware state and safety limits;
- acquisition timing and acknowledgement paths;
- live parameter application;
- trusted scan execution, queues, and emergency recovery;
- local vendor, LabRAD, QCoDeS, Labber, Bluesky, notebook, or script control
  practices already trusted by a lab.

Scopecat can own records and explanations around those systems:

- explicit measurement records, lifecycle events, context, and decision facts;
- code references, selected user-code snapshots, entrypoints, and dependency
  readiness evidence;
- parameter/context snapshots, selected values, generated artifacts, and source
  identity;
- comparisons with selected references;
- analysis inputs, outputs, correction choices, exclusions, fit results,
  quality evidence, annotations, and handoff packages.

The short version: Scopecat records, explains, compares, and packages. Existing
systems execute and mutate. Exceptions need a narrower validation owner, and
safety- or authority-changing exceptions need an ADR.

## Cross-Machine Boundary

Cross-machine value should start from portable records, explicit export/import,
handoff packages, and optional shared-storage references. This makes Scopecat
record-aware across machines, not a distributed experiment-control system.

Shared storage or NAS can be a transport or backup aid when a lab already has
it. Early paths should still work through local records or explicit handoff
without requiring a server.

## Recording Boundary

Scopecat should prefer explicit recording over passive adaptation. Experiment
code, helper libraries, or lab-owned bridges should deliberately send data,
sweep semantics, lifecycle/status events, parameters, code/context references,
progress markers, and saved decisions into Scopecat.

Avoid making the default integration model depend on polling instruments,
importing live control scripts, scraping GUIs, reading mid-write mutable files,
or inferring authoritative truth from opaque legacy files.

Any recording path a lab relies on should state its disable, buffering,
failure, and acknowledgement behavior.

## Complexity Ownership

Scopecat should keep its core responsibility close to structured measurement
evidence: explicit records, manifests, statuses, relations, provenance,
readability, and reviewable decisions.

Local conventions, domain-specific formats, free-text redaction policy,
physical setup semantics, and framework-specific bridge behavior should enter
through explicit adapter or policy surfaces. They should not silently become
core product scope because one workflow needed them.

## Non-Goals By Default

Scopecat is not currently trying to be:

- a replacement measurement GUI or control GUI;
- an instrument-control or device-driver framework;
- a LabRAD, QCoDeS, Labber, Bluesky, or vendor-system compatibility layer;
- a passive scraper for arbitrary measurement artifacts;
- a complete reader/export/conversion suite;
- a semantic parser for arbitrary user artifacts;
- a built-in lab keyword list or universal redaction policy;
- an automatic calibration or parameter write-back system;
- a scheduler, queue, remote execution service, or remote desktop;
- a required central storage server, deployed database, or sync service;
- an authoritative source of hardware, setup, sample, or topology truth;
- a lab operations platform, ELN, LIMS, publication workflow, or report
  generator;
- a universal parameter, setup, sample, or topology ontology.

Some of these may become validated product surfaces later. They are not default
adoption prerequisites.

