# Code Asset Registry

## Status

Follow-on subsystem.

## Responsibility

Code Asset Registry manages code identity and versioned reusable code assets:
experiment scripts, analysis scripts, fitting routines, calibration routines,
instrument drivers, service modules, templates, source references, versions,
content hashes, entrypoints, and compatibility metadata.

## Standalone Adoption

Users can stop copying scripts and drivers across directories by registering
external repositories, local paths, versions, and entrypoints.

## Does Not Own

- execution records
- live instrument services
- datasets
- resource leases
- environment snapshots except as metadata references
