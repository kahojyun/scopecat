# Adapter Output Boundary Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable adapter/import API.

The candidate validates a small adapter-produced input boundary. The fixture is
file-shaped so the boundary is observable in tests, but the earned contract is
logical: an adapter must provide reviewed adapter facts, normalized primary
data, source identity, declared preview metadata, linked-context references,
and findings. A later writer-like API could satisfy the same logical contract
without using the same directory layout.

The candidate:

- validates a fixture-local adapter output boundary manifest;
- reads one adapter-authored legacy import manifest from the adapter output
  root;
- delegates logical measurement/preview validation to the existing
  adapter-authored legacy import candidate;
- observes declared adapter output file facts for the manifest, normalized
  primary data, and linked-context references;
- reports missing or mismatched adapter output files as review findings.

It deliberately does not copy data into Scopecat storage, parse legacy source
formats, infer schemas, repair references, import linked-context payloads,
define GUI behavior, or accept a stable public adapter API.
