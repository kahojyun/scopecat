# Product Brief And Boundaries

## Status

Drafting product brief. Not a roadmap, PRD, capability map, API contract,
storage design, UI spec, architecture decision, or validation charter.

## Purpose

State durable product direction and non-goals so later strategy, validation,
and architecture work does not drift into a framework replacement, a full lab
platform, or a single mandatory adoption path.

## Product Direction

Scopecat is a progressively adoptable workflow-structuring, recording,
analysis, and handoff layer for scientific measurement workflows.

It helps users turn messy experiment code, data, parameters, analysis choices,
decisions, and handoff bundles into explicit records and workflows that are
easier to run, inspect, resume, select, package, compare, and review.

Provenance, explainability, lineage, reviewability, and auditability are
important benefits, but they should usually be earned through concrete workflow
return. Early adoption should be justified by recovery, selection, handoff,
diagnostic value, readable progress, or bounded automation value, not by
provenance as a separate clerical obligation.

Scopecat should complement existing measurement, control, data, calibration,
and analysis systems. It may grow broader product surfaces over time, but
framework replacement is not the default story.

## Adoption Model

Scopecat should be adoptable through narrow, independently useful routes. Each
route should name:

- the first useful output;
- the user behavior it changes;
- what users or lab code must provide;
- what Scopecat will not touch;
- how the path fails, degrades, or can be disabled safely.

Different users may start on different routes. A future complete workflow may
compose several routes, but no first adoption path should require users to
adopt the whole platform.

## System Boundary

Existing experiment systems remain the execution and mutation layer until a
later accepted decision says otherwise. They continue to own:

- instrument communication and driver behavior;
- hardware state and safety limits;
- acquisition timing and acknowledgement paths;
- live parameter application;
- trusted run queues, scan execution, and emergency recovery;
- local vendor, LabRAD, QCoDeS, Labber, Bluesky, notebook, or script control
  practices already trusted by a lab.

Scopecat can own evidence around those systems:

- explicit measurement records, lifecycle events, context, and decision facts;
- code references, selected user-code snapshots, entrypoints, and dependency
  readiness evidence;
- parameter/context snapshots, selected values, generated artifacts, and source
  identity;
- comparison with previous-good, previous-failed, selected, or expected
  references;
- analysis inputs, outputs, correction choices, exclusions, fit results,
  quality evidence, annotations, and handoff packages.

The working boundary is: Scopecat records, compares, explains, proposes, and
packages. Existing systems execute and mutate. Any exception needs a narrower
validation owner and, where safety or authority is involved, an ADR.

## Cross-Machine Boundary

Cross-machine value should start from portable records, explicit export/import,
handoff packages, and optional shared-storage references. This makes Scopecat
distributed-record-aware, not a distributed experiment-control system.

Multiple computers may resolve, copy, or inspect record evidence. That does
not mean multiple computers can safely operate the same instruments through
Scopecat. Remote execution, multi-user command arbitration, account management,
central databases, background indexers, live sync services, and resource
leases are later architecture questions, not default adoption requirements.

Shared storage or NAS can be a transport, discovery, or backup aid when a lab
already has it. Early routes should still work through local records or
explicit handoff without requiring a server.

## Recording Boundary

Scopecat should prefer explicit recording over passive adaptation. Experiment
code, helper libraries, or lab-owned bridges should deliberately send data,
sweep semantics, lifecycle/status events, parameters, code/context references,
progress markers, and saved decisions into Scopecat.

Avoid treating any of these as default integration foundations:

- polling instruments;
- importing live control scripts;
- reading mid-write mutable files as the primary integration path;
- scraping framework GUIs or local folders as the normal model;
- building a matrix of built-in framework-specific auto-adapters;
- inferring authoritative truth from opaque legacy files.

Any promoted recording path must state its disable, buffering, failure, and
acknowledgement behavior before a lab is asked to rely on it.

## Complexity Ownership

Scopecat should keep its core responsibility close to structured measurement
evidence: explicit records, manifests, statuses, relations, provenance,
readability, replayability, and reviewable decisions.

Local conventions, domain-specific formats, free-text redaction policy,
physical setup semantics, and framework-specific bridge behavior should enter
through explicit adapter or policy surfaces. They should not silently become
core product scope because one workflow needed them.

This does not mean users must do all integration work. Scopecat should make
the structured recording path, basic read path, adapter points, and policy
handoff clear enough that lab-owned complexity can connect deliberately.

## Not Default Adoption Requirements

The following are not default prerequisites, adoption requirements, or
replacement targets:

- a replacement for an existing measurement GUI or control GUI;
- an instrument-control or device-driver framework;
- a LabRAD, QCoDeS, Labber, Bluesky, or vendor-system compatibility layer;
- a passive scraper for arbitrary measurement artifacts;
- a complete reader/export/conversion suite;
- a semantic parser for arbitrary user artifacts;
- a built-in lab keyword list or universal redaction policy;
- an automatic calibration or parameter write-back system;
- a workflow scheduler, queue, remote execution service, or remote desktop;
- a required central storage server, deployed database, or sync service;
- an authoritative source of hardware, setup, sample, or topology truth;
- a lab operations platform, ELN, LIMS, publication workflow, or report
  generator;
- a universal parameter, setup, sample, or topology ontology.

Some of these may become validated product surfaces later. The boundary is
about adoption prerequisites, silent scope creep, and authority.

## Current Value Areas

Current direction should stay close to these value areas:

- explain an existing run or work bundle without mutating it;
- recover selected context, code identity, companion artifacts, ambiguity, and
  sharing boundaries;
- create portable pre-analysis handoff snapshots for selected runs;
- support explicit export/import and optional shared-storage discovery without
  remote execution;
- compare evidence and gaps without claiming authoritative setup truth;
- support parameter memory, drift queries, branches, run linkage, and explicit
  checkpoints before mutation ownership;
- support running-run read/monitor workflows from explicitly recorded data
  without taking over hardware control.
