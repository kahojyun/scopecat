# Calibration Step Fit Result Link Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- a calibration step record may reference declared fit-result summaries;
- fit-result summaries can cite step observation links and measurement records
  as inputs;
- fit-result summaries can expose declared parameter estimates for review;
- proposed writes can reference fit results as declared evidence;
- fit-result review state is distinct from write proposal, continuation, and
  apply behavior.

The candidate is side-effect free. It does not read measurement payloads,
execute fitting code, score fit quality, choose models, decide continuation,
apply parameter writes, emit compatibility output, schedule work, or control
hardware.
