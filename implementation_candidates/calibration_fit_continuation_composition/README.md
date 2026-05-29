# Calibration Fit Continuation Composition Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It composes two existing fixture-backed read models:

- calibration work continuation;
- calibration fit validation dataset curation.

The package exists to test whether a user-owned fit recovery can simultaneously
keep a calibration episode moving and preserve selected failed/refit attempts
for later lab-internal validation. It should not be treated as a final workflow
model, dataset registry, replay harness, GUI contract, fitting API, score model,
write-back path, or hardware-control behavior.
