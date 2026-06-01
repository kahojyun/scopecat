# Calibration Step Timeline Trace Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- declared calibration events can be assembled into per-step timeline traces;
- event ordering can be checked across intent creation, context resolution,
  observation linkage, fit-result declaration, write review, and accepted
  handoff;
- timeline findings can surface missing timestamps, missing expected events,
  and out-of-order events.

The candidate is side-effect free. It does not schedule work, execute
calibration code, run fitting, read measurement payloads, decide continuation,
start parameter-state intake, emit compatibility output, roll back writes, or
control hardware.
