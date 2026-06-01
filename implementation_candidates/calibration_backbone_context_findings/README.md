# Calibration Backbone Context Findings Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It pressure-tests degraded cases across the validated calibration-derived
parameter-state measurement-context backbone:

- missing calibration observation;
- accepted handoff not ready;
- parameter-state intake unavailable;
- stored snapshot unavailable;
- prepared run selecting the wrong parameter-state snapshot;
- later measurement record missing or linking a different parameter-state
  snapshot.

The candidate is side-effect free and review-only. It does not read
measurement payloads, execute fitting or calibration code, start runs, control
hardware, write parameters, produce compatibility outputs, mutate storage,
traverse a relation graph, or define shared route schemas.
