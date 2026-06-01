# Prepared Run Operator Pre-Run Approval Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow operator decision record over an acknowledgement-aware manual
pre-run review summary:

- consume one acknowledgement-aware review-gate summary;
- require operator decision identity to match the reviewed prepared-run
  context, measurement, and parameter-state snapshot;
- allow approval only when the review summary is ready for operator pre-run
  decision;
- preserve rejection and deferral rationale without mutating context;
- avoid automatic run start, hardware control, parameter write-back,
  compatibility output, dependency operations, fresh reads, setup/workspace
  mutation, environment operation, code execution, GUI behavior, managed runner
  behavior, durable storage, and shared approval schema extraction.
