# Derived Artifact Source Links Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for a narrow Measurement Records
slice:

- build a structured summary from an explicit derived-artifact manifest;
- connect a derived artifact to explicitly listed source measurements;
- keep source measurement roles, relation states, and review findings
  visible;
- keep the builder side-effect free;
- avoid artifact parsing, source-file reads, checksum validation, storage
  mutation, schema inference, recursive relation traversal, analysis-DAG
  inference, scientific validity claims, GUI behavior, or shared measurement
  schema.

The package exists to test whether Scopecat can preserve useful artifact
source links for handoff and later review without claiming analysis provenance
ownership.
