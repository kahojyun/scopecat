# Calibration Step Observation Link Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration-to-measurement bridge:

- a calibration step intent can declare planned observation needs;
- a calibration step record can link measurement records as observed outputs;
- linked measurement facts are copied only as review summaries;
- missing measurement output is a review finding;
- calibration does not own primary measurement data, measurement storage,
  fitting, execution, continuation, or write-back.

The candidate is side-effect free. It does not read measurement payloads, infer
preview metadata, execute calibration code, fit data, schedule work, retry
steps, apply parameter writes, or control hardware.
