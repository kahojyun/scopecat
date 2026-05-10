# Instrument Runtime

## Status

Follow-on subsystem.

## Responsibility

Instrument Runtime manages live laboratory resources: instrument registry,
resource registry, communication service lifecycle, driver/service binding,
health, leases, conflict prevention, desired-state application, and actual
state snapshots.

## Standalone Adoption

Users can keep old experimental code but acquire leases before touching shared
instruments.

## Does Not Own

- durable parameter knowledge
- general code version identity
- scan semantics
- datasets
- code execution records
