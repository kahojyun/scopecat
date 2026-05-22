# Comparable Code Surface Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first comparable code-surface
slice:

- compare two explicit code fact sets;
- keep the builder side-effect free;
- report objective findings over declared paths, capture states, and integrity
  hints;
- preserve source authority and capture-state limits in every finding;
- avoid Git inspection, semantic source diff, dependency discovery,
  environment readiness, code import, code execution, workspace
  materialization, restore behavior, workflow/DAG contracts, or GUI behavior.

The package exists to test whether recorded or managed code surfaces can be
compared without pretending every included file is content-comparable.
