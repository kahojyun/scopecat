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
handoff, diagnostic clarity, readable progress, or runnable calibration work.
Provenance and auditability matter only when they make those workflows easier.

## Primary Adoption Context

Scopecat is primarily being shaped for the project owner and their lab. Product
direction can rely on repeated local workflow pain, maintainability pressure,
and migration risk in that lab without first proving broad market demand.

This makes deeper integration with the lab's measurement core a legitimate
long-term ambition. It does not remove the need for evidence before committing
to specific runtime, driver, scan, service, or migration scope, but the evidence
may come from local high-value workflows rather than a broad external user base.

## User QoL Outcomes

Prefer work that lets users:

- find and move useful runs without rebuilding context by hand;
- inspect readable parts of long measurements before the full run finishes;
- choose, restore, or migrate the experiment code that actually matters;
- recover parameter states, compare drift, and exclude known-bad states;
- compare a current setup or bundle against a known-good reference;
- hand off analysis context without requiring a complete provenance program.

## Ownership Assumptions

Existing experiment systems own low-level control and mutation by default:
instrument communication, hardware state, acquisition timing, live parameter
application, trusted scan execution, and emergency recovery.

Scopecat may validate a local sequential executor when it runs user-authored
Python/helper steps and improves a concrete workflow such as calibration
continuation. Inside an IPython or notebook-like local arbitrary-code
environment, code execution itself is not the main product boundary. Remote
execution, open-ended autonomy, concurrency, resource arbitration, automatic
retry/mutation policy, and Scopecat-decided parameter write-back are separate
decisions.

Scopecat's executor value should come from experiment semantics, not from
being a general code runner. It may wrap an existing runtime or workflow
library while owning the step contract, experiment intent links, lifecycle
states, review gates, failure/continuation records, output registration, and
links to runs, parameters, code references, known-good references, and analysis
handoff.

Scopecat can own records and explanations around those systems: measurement
records, context, lifecycle events, selected code references, parameter
snapshots, declared parameter-write records, generated artifacts, selected
references, analysis choices, quality notes, annotations, and handoff packages.

Cross-machine value should start from portable records, explicit export/import,
handoff packages, existing shared-storage discovery or references, and
openability checks. This makes Scopecat record-aware across machines, not a
distributed experiment-control system.

Recording should be explicit. Experiment code, helper libraries, or lab-owned
bridges should deliberately send data, sweep semantics, lifecycle/status
events, parameters, code/context references, progress markers, and saved
decisions into Scopecat.

## Integration Boundary

Local conventions, domain-specific formats, free-text redaction policy,
physical setup semantics, and framework-specific bridge behavior should enter
through explicit adapter or policy surfaces. They should not silently become
core product scope because one workflow needed them.

## Expansion Posture

Early design should preserve future expansion paths without making them default
adoption requirements. Scopecat can start at the experiment-semantics and
workflow layer while leaving room for deeper runtime ownership if later evidence
shows that adapters, references, readiness checks, or handoff records are not
enough.

Higher-bar expansions include owning more scan execution semantics, stronger
device-service lifecycle support, deeper concurrency/resource behavior, or
selected driver/control capabilities. These are not ruled out permanently, but
they need explicit validation and decision records because they change
responsibility for hardware state, timing, recovery, and lab operations.

Future scan, driver, or control capabilities should be optional adoption paths
and backend choices, not mandatory replacements for existing lab systems. A lab
should be able to keep using LabRAD, QCoDeS, Labber, vendor systems, or
lab-owned scripts while adopting only the Scopecat layers that improve its
current workflow.

## Not Default Adoption Prerequisites

Early adoption should not require:

- replacing existing measurement GUIs, control GUIs, drivers, hardware-control
  frameworks, LabRAD, QCoDeS, Labber, Bluesky, vendor systems, or lab-owned
  scripts;
- a complete reader/export/conversion suite or semantic parser for arbitrary
  user artifacts;
- passive scraping of arbitrary measurement artifacts as the main integration
  model;
- Scopecat-decided calibration write-back or parameter mutation;
- general scheduling, remote execution, open-ended autonomy, central storage,
  or sync services.

These are not permanent bans. Scopecat may later expand related capabilities
when a narrower workflow proves the need and the boundary remains controlled.
Examples include managing device-service code references, preparing or
rendering declarative scan plans into parameters for existing systems,
validating generated parameters before handoff, and using explicit adapters or
bridges.

## Product Non-Goals

Without a later explicit decision, Scopecat should not become:

- the authoritative runtime for drivers, low-level hardware control,
  timing-critical execution, or lab-owned service operations;
- the authoritative source of hardware, setup, sample, or topology truth;
- a replacement for lab operations, ELN, LIMS, publication, or
  report-generation systems;
- a universal parameter, setup, sample, or topology ontology.
