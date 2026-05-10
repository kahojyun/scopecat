# Vision

## Status

Draft product thesis.

## Thesis

Scopecat is a local experiment memory system that can grow into a progressively
adoptable experimental automation platform.

The first useful product should help scientists record measurement runs from
ordinary Python scripts, inspect live traces while work is running, preserve
checkpointed data after ordinary interruptions, and reopen durable records by
stable IDs.

The long-term platform should separate measurement history, scan semantics,
durable parameters, code identity, live instrument runtime, and managed
execution into independently useful systems that compose cleanly.

## Product Principles

- Standalone value first, composition value second.
- Progressive adoption over big-bang migration.
- Measurement history must not require managed execution or instrument control.
- Previewed plans and executed plans should share semantics when remote
  execution exists.
- Desired instrument state and actual instrument state must remain distinct.
- Workflow orchestration should coordinate subsystem capabilities, not own
  their core domain models.

## First Adoption Promise

Scopecat is worth continuing when a user can migrate a simple new measurement
script by rewriting the recording section, then reliably write, watch, reopen,
and analyze the resulting data without adopting a runner, scheduler, device
framework, or hosted service.

## Non-Goals For The First Slice

- Full workflow engine.
- General scheduler.
- Hosted multi-user service.
- Device-control framework.
- Managed execution requirement.
- Old-history import as a prerequisite.
- Public stability promises for all future subsystem APIs.
