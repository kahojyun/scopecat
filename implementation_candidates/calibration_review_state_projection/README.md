# Calibration Review State Projection Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- declared review bundle, evidence-completeness, and timeline facts can be
  projected into per-step review-state cards;
- review states can expose labels for available review actions;
- timeline, evidence, fit, write, and handoff concerns stay visible together.

The candidate is side-effect free. It does not render a GUI, execute actions,
retry measurements, rerun fitting, decide continuation, start parameter-state
intake, emit compatibility output, schedule work, roll back writes, or control
hardware.
