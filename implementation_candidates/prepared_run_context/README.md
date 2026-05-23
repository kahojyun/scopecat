# Prepared Run Context Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first prepared run context
slice:

- build a structured manual run-preparation summary from explicit fixture
  input;
- keep the builder side-effect free;
- validate that selected run context references are explicit;
- connect selected managed code version and editable workspace observation
  facts without inspecting the filesystem;
- group parameter state, setup binding, station registry, managed code
  version, editable workspace observation, declared environment, and
  measurement intent without sharing their schemas;
- report workspace drift and missing required context as preparation findings;
- avoid hardware control, parameter write-back, setup mutation, environment
  sync, code import, code execution, workflow/DAG contracts, or GUI behavior.

The package exists to test whether selected code/workspace context can be
assembled with selected measurement context for a manual run-preparation
surface without accepting a universal context schema, readiness contract,
restore behavior, runnable environment claim, or execution framework.
