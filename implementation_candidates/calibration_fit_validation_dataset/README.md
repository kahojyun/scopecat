# Calibration Fit Validation Dataset Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the calibration fit validation
dataset slice:

- summarize user-owned fit incidents as a candidate queue;
- separate immediate recovery choices from validation-dataset curation;
- project selected incidents into minimal validation case records;
- keep the builder side-effect free;
- avoid executing fits, reading source data, selecting ROIs, applying writes,
  remeasuring, scheduling work, or controlling hardware.

The package exists to test whether the first fixture-backed read model can be
expressed cleanly as code. It should not be treated as a final module layout,
dataset registry, fitting API, score model, GUI contract, or replay harness.
