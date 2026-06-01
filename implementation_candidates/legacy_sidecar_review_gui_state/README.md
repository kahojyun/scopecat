# Legacy Sidecar Review GUI State Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow passive view-state projection for legacy sidecar
post-run review:

- consume an already-built legacy sidecar post-run review summary;
- expose deterministic lifecycle, locator, primary-data, and supporting
  evidence cards;
- expose possible next action labels for local GUI, CLI, or notebook surfaces;
- keep every action label side-effect-free and unexecuted.

The candidate intentionally does not define GUI components, perform backend
lookup, observe files, accept legacy imports, mutate storage, repair
references, write parameters, decide measurement validity, or make review
findings run-blocking.
