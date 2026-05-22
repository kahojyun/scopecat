# Named Run-Start Input Set Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first named run-start input
set slice:

- build a structured run-preparation summary from explicit fixture input;
- keep the builder side-effect free;
- validate that selected run-start context references are explicit;
- group parameter state, setup binding, station registry, managed code version,
  declared environment, and measurement intent without sharing their schemas;
- record missing required context as preparation findings;
- avoid hardware control, parameter write-back, setup mutation, environment
  sync, code import, code execution, workflow/DAG contracts, or GUI behavior.

The package exists to test whether selected context records can be assembled
into one named run-start input set without accepting a universal context
schema, lifecycle model, storage model, readiness contract, restore behavior,
or execution framework.
