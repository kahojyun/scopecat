# Scopecat Vision And Boundaries

## Status

Drafting project vision and boundary note. This is not a roadmap, product
requirements document, capability map, API contract, storage design, UI spec, or
architecture decision.

## Purpose

State the clearest project-level product boundaries so later journeys,
adoption routes, and architecture decisions do not drift into an accidental
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

Scopecat should be adopted through narrow, independently useful routes. Each
route should be able to create standalone value for the users who need it, and
different users may start on different routes.

Design work should still consider the full set of routes together so later
composition is possible. A complete workflow may require several routes to
compose, but no initial adoption path should require users to adopt the full
platform.

Top-level pains are composition pressure, not single-route implementation
requirements. They can show why multiple capabilities eventually need to work
together, but each promoted journey still needs a concrete user sequence,
validation fixture, explicit boundary, and standalone value.

Before a route is piloted with a lab, its owner should state the minimum
adoption contract: what the lab must record or provide, what Scopecat will not
touch, how the path fails or can be disabled safely, and what first useful
output the lab gets before broader adoption.

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
- create reviewable parameter-memory records, advisory proposals, annotations,
  handoff snapshots, and lineage records.

Scopecat records, compares, explains, proposes, and packages. Existing systems
execute and mutate.

## Automation Responsibility Boundary

Automation is not outside Scopecat's long-term direction. Existing lab
workflows already contain automation through scripts, notebooks, calibration
loops, queued cells, framework schedulers, and local operator conventions.
Scopecat's opportunity is to make that automation explicit, reviewable,
replayable, diagnosable, and progressively safer before it claims authority over
hardware control.

Keep these responsibilities separate:

- Instrument runtimes, device drivers, vendor software, hardware interlocks,
  and lab-owned control code own authoritative hardware constraints such as
  output ranges, ramp behavior, timing, channel capabilities, and emergency-safe
  states.
- Queue, plan, and orchestration layers may own execution order, lifecycle
  state, readiness checks, pause or abort behavior, failure policy, and audit
  records.
- Experiment authors and lab operators remain responsible for scientific
  intent, physical setup assumptions, calibration meaning, and whether a planned
  sequence is appropriate for the current apparatus.
- Scopecat may own evidence, frozen intent, review gates, mock or shadow
  replay, lifecycle records, diagnostics, proposals, and accountability for
  what was requested, checked, approved, run, skipped, stopped, or failed.

When Scopecat does not own the instrument runtime, it should not claim to
enforce hardware safety limits. It may record bounds, readiness facts, and
preflight results supplied by user code, lab-owned runtimes, drivers, or
operators, and it should preserve which source supplied them.

Journey-level automation placement belongs in the experience map or a narrower
`JC` owner. Real hardware apply, autonomous calibration, rollback, resource
locking, and unattended queue execution require accepted boundaries that state
the runtime owner, safety assumptions, stop behavior, and audit record.

## Explicit Recording Boundary

Scopecat should not actively adapt arbitrary existing measurement frameworks as
its core live-observation model.

For measurement-time feedback, experiment code should explicitly record the
needed information into Scopecat: data, sweep semantics, lifecycle/status
events, parameters, code/context references, progress/readiness markers, and
any saved decision-relevant facts. Scopecat can then read, display, analyze,
replay, and package only what was deliberately recorded.

Explicit recording must not silently turn Scopecat into a fragile dependency of
the acquisition loop. Any promoted recording path should state its safe
disable, buffering, failure, and acknowledgement behavior before a lab is asked
to rely on it.

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

## Complexity Ownership Boundary

Scopecat should keep its core responsibility close to structured measurement
evidence: explicit records, manifests, statuses, relations, provenance,
readability, replayability, and reviewable decisions.

It should not absorb every high-complexity edge around that evidence by
default. Prefer clear user or lab extension points when the problem depends on
local conventions, domain-specific formats, or sharing policy:

- Framework bridges should send explicit records into Scopecat rather than
  making Scopecat actively adapt each existing control framework.
- Reader support should prioritize a stable, useful basic read path and enough
  metadata for users to transform or export data into their own analysis tools.
  Scopecat should not treat every reader view, conversion, or export format as
  built-in product scope.
- User-provided artifacts should be cataloged by role, relation, provenance,
  size or checksum, and explicit status before Scopecat claims semantic
  understanding. Domain-specific parsing requires a deliberate adapter,
  fixture, or decision; arbitrary files should not be executed, unpickled,
  normalized, or interpreted by default.
- Redaction and publishability should be owned by explicit export or publish
  workflows. Scopecat may handle structurally known sensitive fields and
  explicit sensitivity labels, but it should not ship a fixed built-in lab
  keyword list for samples, devices, projects, acronyms, or local shorthand.
  Labs or users provide keyword profiles, replacement rules, and publish
  profiles when a workflow opts into free-text or payload redaction.

This boundary is not an excuse to make users do all integration work. Scopecat
should make the structured recording path, basic read path, adapter points, and
policy handoff clear enough that lab-owned complexity can connect without
becoming hidden product scope.

## Not Default Adoption Requirements

The following are not default adoption requirements, prerequisites, or
replacement targets for every route:

- a replacement for the lab's existing measurement GUI or control GUI;
- an instrument-control framework;
- a device-driver framework;
- a LabRAD, QCoDeS, Labber, Bluesky, or vendor-system compatibility layer;
- a passive scraper of arbitrary existing measurement artifacts;
- a complete set of reader views, conversions, or export formats;
- a semantic parser for arbitrary user-provided artifacts;
- a built-in lab keyword list or universal redaction policy;
- an automatic calibration or parameter write-back system;
- a workflow scheduler, queue, or remote execution service;
- an authoritative source of hardware truth;
- a lab operations platform for booking, cooldown planning, shift management,
  personnel coordination, training, incidents, or multi-equipment scheduling;
- a full ELN, LIMS, publication workflow, or report generator;
- a universal parameter, setup, sample, or topology ontology.

Some of these areas may become product surfaces, integrations, or later
capabilities after specific journeys and decisions justify them. For example,
Scopecat may provide its own run browser or live observation surface for
Scopecat-recorded runs without becoming a replacement for a lab's existing
instrument-control GUI. It may also make existing queue or calibration
automation more explicit before it owns any hardware-control runtime. The
boundary is about adoption prerequisites, silent scope creep, and authority, not
a promise to avoid these areas forever.

## Current Clear Value Areas

The clearest current value areas are listed here as direction, not as a single
ordered first slice:

- explain an existing run or work bundle without mutating it;
- preserve selected context, code-shaped provenance, companion artifacts,
  ambiguity, and sharing boundaries;
- create immutable pre-analysis handoff snapshots for selected runs;
- compare evidence and gaps without claiming authoritative truth;
- support parameter memory, advisory evidence, and optional reviewable
  proposals before any parameter or calibration mutation;
- support running-run read/monitor workflows and optional measurement-time
  decision evidence from explicitly recorded measurement data without taking
  over hardware control.

These value areas can compose over time. None requires every user to start from
the same route, and none requires Scopecat to replace the lab's working
acquisition stack as a prerequisite.
