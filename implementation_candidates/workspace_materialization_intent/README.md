# Workspace Materialization Intent Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first workspace
materialization-intent slice:

- plan destination paths for a selected managed code version;
- keep the builder side-effect free;
- report objective findings for planned files, declared destination
  collisions, redacted files, and unavailable files;
- preserve selected-version provenance in every file plan;
- avoid filesystem inspection, directory creation, overwrite, merge, Git
  behavior, dependency discovery, environment restoration, code import, code
  execution, workspace materialization, restore behavior, workflow/DAG
  contracts, or GUI behavior.

The package exists to test whether users can review where a managed code
version would be materialized before Scopecat writes files.
