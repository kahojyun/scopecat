# Calibration Work Continuation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the calibration work continuation
slice:

- assemble a structured continuation summary from scattered fixture context;
- keep the builder side-effect free;
- avoid executing calibration code, reading source files, fitting data,
  applying writes, retrying steps, scheduling work, or controlling hardware;
- keep Markdown review rendering in fixture/test support, not in this package.

The package exists to test whether the current fixture-backed read-model
boundary can be expressed cleanly as code. It should not be treated as a final
module layout, workflow model, runner API, authoring contract, dependency graph,
or parameter schema.
