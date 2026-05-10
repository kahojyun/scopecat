# Managed Code Runner

## Status

Follow-on subsystem.

## Responsibility

Managed Code Runner executes code in a controlled, observable, and reproducible
way: execution plans, records, environment snapshots, stdout/stderr capture,
artifacts, process supervision, resource limits, status, cancellation, and
batch or remote mechanics.

## Standalone Adoption

Users can run old analysis, fitting, or acquisition scripts through the runner
to capture logs, artifacts, environment information, and execution status.

## Does Not Own

- general code asset identity
- live instrument leases
- measurement datasets
- durable parameter definitions
- scan semantics
