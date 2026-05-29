# Calibration Fit Recovery Workflow Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow user-facing recovery read model for calibration fit trouble:

- no clear signal pushes the user toward parameter adjustment and remeasurement;
- visible signal with fit failure can preserve failed and adjusted attempts
  while allowing continuation after user acceptance.

The package does not execute fits, score fit quality, choose ROI or initial
guesses, remeasure, apply parameter writes, provide a replay harness, implement
a dataset registry, define a GUI workflow, or control hardware.
