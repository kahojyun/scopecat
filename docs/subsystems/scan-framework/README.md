# Scan Framework

## Status

High-priority follow-on subsystem.

## Responsibility

Scan Framework structures experimental scan semantics: scan plans, scan
variables, fixed parameters, scan-point expansion, parameter binding, desired
instrument-state rendering, preview, state diffing, acquisition-block
structure, and scan metadata.

## Standalone Adoption

Users can replace ad-hoc nested loops with structured scan plans while still
using existing drivers and data-saving code.

## Does Not Own

- durable calibration parameters
- live instrument leases
- driver lifecycle
- code asset identity
- execution environments
- full workflow orchestration
