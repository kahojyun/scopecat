# Reference-Based Rerun Preparation Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first reference-based rerun
preparation slice:

- build a structured summary from an explicit selected reference measurement
  and its linked context records;
- seed a manual rerun target from reference-linked measurement intent,
  parameter state, setup binding, station registry, managed code, editable
  workspace observation, and declared environment context;
- report missing context, workspace-observation review findings, and declared
  environment review findings without turning them into run-blocking,
  readiness, or reproducibility claims;
- keep the builder side-effect free;
- avoid hardware control, parameter write-back, setup mutation, dependency
  sync, code import, code execution, automatic drift correction, cause
  attribution, workflow/DAG contracts, or GUI behavior.

The package exists to test whether a selected reference measurement can seed a
manual rerun context without accepting reproducibility guarantees or executor
authority.
