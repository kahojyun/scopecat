# Product Direction

## Status

Current product direction.

## Purpose

State what Scopecat is trying to become and the default ownership assumptions
that guide discovery. Narrower validation, decision, contract, and
prototype-boundary docs should own details when they are needed.

## Summary

- Scopecat is a brownfield-friendly evidence, review, and handoff layer around
  existing scientific measurement systems.
- Early value should come from practical workflow return: recovery, selection,
  handoff, diagnostic clarity, readable progress, and runnable calibration work.
- Existing experiment systems own low-level control and mutation by default;
  Scopecat records, explains, packages, reviews, and bridges around them.
- Cross-machine value starts with portable records, handoff packages, explicit
  export/import, and open-before-import review.
- Deeper runtime, driver, scan, service, or migration ownership is possible but
  requires a narrower validated workflow and explicit decision.
- Redaction and artifact classification are boundary-specific: portable/export
  artifacts need stronger handling than local repository-safe fixtures or
  review surfaces.

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
That local evidence may include risk from aging or unmaintained measurement
infrastructure. In that context, selectively replacing parts of an existing
control stack can be a maintainability improvement rather than only an
expansion of product burden.

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
- compare a current setup or bundle against a selected reference;
- hand off analysis context without requiring a complete provenance program.

## Ownership Assumptions

Existing experiment systems own low-level control and mutation by default:
instrument communication, hardware state, acquisition timing, live parameter
application, trusted scan execution, and emergency recovery.

Scopecat can own records and explanations around those systems: measurement
records, context, lifecycle events, recorded code references, parameter
snapshots, declared parameter-write records, generated artifacts, selected
references, analysis choices, quality notes, annotations, and handoff packages.

Scopecat can also support explicit adapters or bridges when they make a
workflow easier to record, review, hand off, or migrate. Those adapters do not
make the underlying hardware protocol, control loop, runtime, or replacement
plan a product default. Capability-specific validation should decide when
Scopecat moves closer to execution, driver/service migration, code workspace
management, environment operation, or GUI monitoring.

Use these owner documents for details:

- [`adoption-model.md`](adoption-model.md) for brownfield adoption paths;
- [`journey-map.md`](journey-map.md) for product user journeys, primary
  workflows, and use cases to prove;
- [`capability-map.md`](capability-map.md) for product capability maturity and
  advancement questions;
- [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
  for current user journeys, use cases, scenarios, operations, seams, and
  validation questions;
- [`../discovery/policies/managed-experiment-code-posture.md`](../discovery/policies/managed-experiment-code-posture.md)
  for historical discovery strategy around Git-like experiment-code versions.

Cross-machine value should start from portable records, handoff packages,
explicit export/import, existing shared-storage discovery or references, and
openability checks. This makes Scopecat record-aware across machines, not a
distributed experiment-control system.

The target handoff experience is open-before-import. A Scopecat-authored
handoff package should be useful as a standalone portable artifact: a future
Python SDK or GUI should be able to open the package read-only, inspect package
contents, load declared primary data, show package metadata and linked context
references, and make basic declared-preview plots. Users should not need to
accept, import, or organize the package into local Scopecat-managed storage
before quick review or analysis.

Package import, acceptance, and organization are optional later workflows. They
may copy or register package contents into local storage, so they need stronger
mutation, destination, and no-overwrite behavior than read-only package use.

Export/import should eventually support quick measurement orientation on both
sides. Export preview helps choose which measurements to package. Handoff or
export-package contents preview helps the receiving user confirm what a
Scopecat-created package contains before read-only package use or later
acceptance/organization. Incoming-record import preview helps classify
externally supplied candidate records before import authority exists. These are
related preview surfaces with different input authorities, not one generic
import contract. This is an orientation and trust boundary, not a commitment to
report generation, user/domain conclusions, broad GUI ownership, or full import
authority in the first slice.

Recording should be explicit. Experiment code, helper libraries, or lab-owned
bridges should deliberately send data, sweep semantics, lifecycle/status
events, parameters, code/context references, progress markers, and saved
decisions into Scopecat.

## Integration Boundary

Local conventions, domain-specific formats, free-text redaction policy,
physical setup semantics, and framework-specific bridge behavior should enter
through explicit adapter or policy surfaces. They should not silently become
core product scope because one workflow needed them.

Artifact classification and redaction are boundary-specific. Local review
surfaces and repository-safe fixtures should remain useful and explicit;
portable/export artifacts need stronger managed-reference validation and
redaction behavior. The detailed policy owner is
[`../discovery/policies/artifact-boundary-and-redaction.md`](../discovery/policies/artifact-boundary-and-redaction.md).

## Expansion Strategy

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
For the owner lab, that validation may also include maintenance risk from
unmaintained inherited systems. If replacing a local LabRAD-era service,
driver, or scan boundary reduces operational risk and makes the workflow more
understandable, it can be a legitimate optional migration path rather than a
sign that Scopecat is defaulting to universal control-framework ownership.
The intended ownership center remains structured communication intent,
execution context, records, and adapter contracts; concrete transport,
instrument protocol, and timing-critical behavior should stay in the selected
backend unless a later decision explicitly narrows a different boundary.

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
