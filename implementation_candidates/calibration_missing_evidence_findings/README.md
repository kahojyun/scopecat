# Calibration Missing Evidence Findings Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- declared calibration review facts can be checked for missing evidence;
- per-step completeness can show missing observations, missing fit results,
  fit results needing review, pending write review, and missing accepted-write
  handoff;
- findings remain review-only and do not decide retry, remeasurement,
  continuation, parameter-state intake, or hardware behavior.

The candidate is side-effect free. It does not rerun child slices, read
measurement payloads, execute fitting, score fit quality, decide continuation,
start parameter-state intake, emit compatibility output, schedule work, or
control hardware.
