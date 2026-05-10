# Parameter Memory

## Status

Follow-on subsystem.

## Responsibility

Parameter Memory records durable parameter knowledge: schemas, slots, sets,
immutable snapshots, calibration state, update proposals, and parameter
history.

## Standalone Adoption

Users can keep old scripts while reading exported parameter snapshots or
recording calibration knowledge in one durable place.

## Does Not Own

- scan-local variables
- live instrument state
- resource leases
- code execution
- measurement datasets
