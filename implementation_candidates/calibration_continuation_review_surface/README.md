# Calibration Continuation Review Surface Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow notebook/CLI consumption boundary:

- consume existing calibration review-state cards;
- consume the validated calibration-derived parameter-state backbone summary;
- consume missing/partial backbone context findings;
- project a compact route review surface with labels-only actions.

The candidate does not render a GUI, execute notebook cells, execute review
actions, read measurement payloads, run fitting, control hardware, write
parameters, start runs, mutate storage, or define a shared surface schema.
