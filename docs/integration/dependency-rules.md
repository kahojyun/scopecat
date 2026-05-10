# Dependency Rules

## Status

Draft architecture constraints.

## Rules

Measurement History may reference optional provenance from other subsystems,
but basic data recording must not require them.

Scan Framework may run standalone and may optionally integrate with Parameter
Memory, Instrument Runtime, Managed Code Runner, Code Asset Registry, and
Measurement History.

Parameter Memory must not depend on live instrument runtime or scan execution.

Code Asset Registry owns code identity and must not execute code or manage
live instruments.

Instrument Runtime owns live resources, leases, and service lifecycle. It must
not own durable parameter knowledge or general code identity.

Managed Code Runner owns execution records and environment snapshots. It must
not own code asset identity or instrument lease policy.

Workflow Layer may depend on foundational systems.

Foundational systems must not require Workflow Layer for their core standalone
use cases.

## Future Enforcement

These rules start as documentation. If the monorepo later gains enforceable
project metadata, equivalent dependency constraints should be checked in CI.
