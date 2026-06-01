# Calibration Step Intent Resolution Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- a calibration step intent may carry moving context selectors;
- a step-start resolution receipt freezes those selectors to point-in-time
  context records;
- the calibration step record carries only resolved context links plus optional
  observation-link references;
- missing optional context is a review finding;
- lineage movement after step start does not rewrite the step record.

The candidate is side-effect free. It does not read measurement payloads,
resolve selectors from storage, execute calibration code, fit data, schedule
work, retry steps, decide continuation, apply parameter writes, or control
hardware.
