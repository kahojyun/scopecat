# Scopecat Vision And Boundaries

## Status

Drafting project vision and boundary note. This is not a roadmap, product
requirements document, capability map, API contract, storage design, UI spec, or
architecture decision.

## Purpose

State the clearest project-level product boundaries so later journeys,
adoption ladders, and architecture decisions do not drift into an accidental
framework replacement, single required starting point, or full-platform adoption
requirement.

Narrow journey documents, accepted decisions, and future architecture contracts
own implementation-grade detail. This document owns only durable direction that
is already clear enough to guide those documents.

## Product Direction

Scopecat is a progressively adoptable evidence, recording, analysis, and
handoff layer for scientific measurement workflows.

It helps users make measurement work explainable, comparable, reviewable,
replayable, and portable across the messy boundary between experiment code,
data, parameters, analysis, decisions, and later handoff.

Scopecat should complement existing measurement, control, data, and calibration
systems. It may grow into broader product surfaces over time, but it should not
make framework replacement the default adoption story.

## Adoption Model

Scopecat should be adopted through narrow, independently useful ladders. Each
ladder should be able to create standalone value for the users who need it, and
different users may start on different ladders.

Design work should still consider the full set of ladders together so later
composition is possible. A complete workflow may require several ladders to
compose, but no initial adoption path should require users to adopt the full
platform.

Top-level pains are composition pressure, not single-ladder implementation
requirements. They can show why multiple capabilities eventually need to work
together, but each promoted journey still needs a concrete user sequence,
validation fixture, explicit boundary, and standalone value.

## Boundary With Existing Experiment Systems

Existing experiment systems should remain the execution and mutation layer until
a later accepted decision says otherwise. They continue to own:

- instrument communication and driver behavior;
- hardware state and safety limits;
- acquisition timing and acknowledgement paths;
- live parameter application;
- run queues, scan execution, and emergency recovery;
- local vendor, LabRAD, QCoDeS, Labber, Bluesky, notebook, or script control
  practices that are already trusted by a lab.

Scopecat should own the evidence layer around those systems. It may:

- record measurement data, context, lifecycle events, and decision-relevant
  facts explicitly sent to it by user experiment code;
- preserve code references, parameter/context snapshots, selected values,
  generated artifacts, and source identity;
- compare current evidence with previous-good, previous-failed, selected, or
  expected references;
- run or replay analysis over recorded inputs;
- produce fit, quality, anomaly, and decision evidence;
- create reviewable proposals, annotations, handoff snapshots, and lineage
  records.

Scopecat records, compares, explains, proposes, and packages. Existing systems
execute and mutate.

## Explicit Recording Boundary

Scopecat should not actively adapt arbitrary existing measurement frameworks as
its core live-observation model.

For measurement-time feedback, experiment code should explicitly record the
needed information into Scopecat: data, sweep semantics, lifecycle/status
events, parameters, code/context references, and decision-relevant facts.
Scopecat can then analyze, display, replay, and package only what was
deliberately recorded.

Avoid treating any of these as default integration foundations:

- polling instruments;
- importing live control scripts;
- reading mid-write mutable files as the primary integration path;
- scraping framework GUIs or local folders as the normal model;
- building a matrix of built-in framework-specific auto-adapters;
- claiming to infer authoritative truth from opaque legacy files.

A lab may later choose to write a bridge from its own framework into Scopecat's
recording path. That bridge should be treated as user or lab integration code
that sends explicit records, not as Scopecat owning the source framework.

## Not Default Adoption Requirements

The following are not default adoption requirements, prerequisites, or
replacement targets for every ladder:

- a replacement for the lab's existing measurement GUI or control GUI;
- an instrument-control framework;
- a device-driver framework;
- a LabRAD, QCoDeS, Labber, Bluesky, or vendor-system compatibility layer;
- a passive scraper of arbitrary existing measurement artifacts;
- an automatic calibration or parameter write-back system;
- a workflow scheduler, queue, or remote execution service;
- an authoritative source of hardware truth;
- a full ELN, LIMS, publication workflow, or report generator;
- a universal parameter, setup, sample, or topology ontology.

Some of these areas may become product surfaces, integrations, or later
capabilities after specific journeys and decisions justify them. For example,
Scopecat may provide its own run browser or live observation surface for
Scopecat-recorded runs without becoming a replacement for a lab's existing
instrument-control GUI. The boundary is about adoption prerequisites and
authority, not a promise to avoid these areas forever.

## Current Clear Value Areas

The clearest current value areas are listed here as direction, not as a single
ordered first slice:

- explain an existing run or work bundle without mutating it;
- preserve selected context, code-shaped provenance, companion artifacts,
  ambiguity, and sharing boundaries;
- create immutable pre-analysis handoff snapshots for selected runs;
- compare evidence and gaps without claiming authoritative truth;
- support reviewable proposals before any parameter or calibration mutation;
- support measurement-time decision evidence from explicitly recorded
  measurement data without taking over hardware control.

These value areas can compose over time. None requires every user to start from
the same ladder, and none requires Scopecat to replace the lab's working
acquisition stack as a prerequisite.
