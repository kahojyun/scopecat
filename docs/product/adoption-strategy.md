# Product Adoption Strategy

## Status

Current product adoption strategy.

## Purpose

Describe how users can start adopting Scopecat. This is a product strategy
document, not a brownfield current-state assessment, transition architecture,
migration plan, journey catalog, workflow validation map, or implementation
register.

Use this document to answer:

- what first user change Scopecat asks for;
- what user value the adoption path creates;
- what product journeys and capabilities the path exercises;
- what adoption risk remains.

Use [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md)
for current/transition/target brownfield journeys and ownership posture. Use
[`target-journeys.md`](target-journeys.md) for target product journeys and
[`target-capabilities.md`](target-capabilities.md) for product capabilities.

## Adoption Principles

- Start with useful review, selection, handoff, and diagnostic value before
  asking users to replace working measurement systems.
- Prefer explicit Python or adapter-authored recording over passive scraping as
  the first integration model.
- Keep existing systems responsible for low-level hardware control until a
  narrower workflow proves replacement is worth the risk.
- Make cross-machine value concrete through open-before-import packages,
  preview, and explicit import decisions.
- Treat selective migration as optional and capability-specific, not as a
  project-wide rewrite.

## Adoption Paths

### Post-Run Record-First

User change: keep running measurements in the existing system, then record
declared run facts, source references, optional converted primary data, and
review evidence in Scopecat.

User value:

- find selected measurements without reconstructing folders by hand;
- make reviewed primary data visible in a durable local record;
- attach later parameter, code, setup, artifact, or evidence references.

Supports:

- Portable Measurement Handoff;
- Selected Reference Comparison later;
- Measurement Records;
- Experiment Code Context later;
- Parameter State Review later.

Main adoption risk: users may expect Scopecat to understand raw legacy formats,
scientific validity, or execution semantics before those boundaries are owned.

### Portable Handoff-First

User change: select useful measurement data and send a Scopecat-authored
package for read-only review, preview, and later import on another computer.

User value:

- package a selected measurement with declared identity and primary data;
- let the receiver open and inspect before accepting storage mutation;
- make missing context explicit instead of hiding it in folder structure.

Supports:

- Portable Measurement Handoff;
- Handoff Packages;
- Measurement Records.

Main adoption risk: package authority and import authority are easy to collapse
unless read-only open, preview, and accepted import remain separate.

### Review-Before-Import

User change: open a package or candidate record for orientation before accepting
storage mutation.

User value:

- inspect package contents before import;
- build a non-mutating import plan;
- accept only the selected measurement that the user approves.

Supports:

- Portable Measurement Handoff;
- Handoff Packages;
- Measurement Records.

Main adoption risk: users may treat preview as validation of trust,
authenticity, scientific correctness, or complete context unless the boundary
stays explicit.

### Parameter Review Before Apply

User change: review adapter or calibration parameter-state facts before a run
without letting Scopecat apply hardware changes.

User value:

- inspect parameter state before use;
- store and read reviewed parameter facts;
- compose prepared-run context without handing over run-start authority.

Supports:

- Manual Pre-Run Context Review And Approval;
- Parameter State Review;
- Measurement Records context links later.

Main adoption risk: review, compatibility output, live write-back, and hardware
apply can look like one workflow unless mutation authority is explicit.

### Explicit Experiment-Code Recording

User change: record the code context that mattered for a run or step without
adopting Git-facing workflow up front.

User value:

- preserve entrypoint and include-policy context;
- compare selected recorded-code context;
- later materialize or restore a workspace only when the workflow earns it.

Supports:

- Experiment Code Context Recovery And Reuse;
- Manual Pre-Run Context Review And Approval later;
- Experiment Code Context;
- Environment Operation.

Main adoption risk: code recording can be mistaken for package management,
execution readiness, deployment, or version-control replacement.

### Running Monitor

User change: keep a local GUI open while Python-driven measurements emit
lifecycle, progress, partial data, and completion events.

User value:

- inspect progress without taking control of execution;
- review partial-but-useful data before the run completes;
- save selected fit or operator decisions later.

Supports:

- Running Measurement Monitoring And Inspection;
- Running Measurement Monitor;
- Measurement Records;
- optional app runtime.

Main adoption risk: monitoring may be confused with scheduling, scan-plan
control, automatic retune, or hardware safety ownership.

### Selective Legacy Replacement

User change: replace one fragile legacy service, driver, scan boundary, or
helper workflow only when that replacement reduces operational risk.

User value:

- reduce local maintenance risk in a named workflow;
- retire one boundary without forcing a project-wide rewrite;
- keep backend choices explicit.

Supports:

- whichever target journey and capability the selected boundary serves;
- optional future runtime, driver, scan, or service ownership after a decision.

Main adoption risk: a local replacement can be misread as a default product
direction toward universal hardware-control framework ownership.

## Update Rule

Update this strategy when a branch changes how users are expected to start
using Scopecat or when a new adoption path becomes product-relevant.

Do not use this file to track brownfield current state, transition-state
ownership, delivery maturity, implementation entrypoints, tests, fixtures, or
module ownership.
