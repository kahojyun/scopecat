# Measurement History

## Status

Primary first-slice subsystem.

## Responsibility

Measurement History records what happened: experiment runs, datasets, derived
datasets, imported legacy datasets, scan-point records, run metadata, dataset
lineage, and links to optional provenance references.

## Standalone Adoption

Users can keep ordinary Python scripts and old device-control code while
writing new data into Scopecat for durable identity, live inspection, partial
readability, and stable-ID reopen.

## Does Not Own

- durable parameter definitions
- live instrument control
- code execution
- code version identity
- workflow decisions
