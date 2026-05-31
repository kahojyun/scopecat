# Calibration Parameter-State Storage Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow storage boundary for calibration-derived parameter-state
intake:

- validate the nested calibration parameter-state intake input;
- require an approved storage request with declared no-overwrite paths;
- write one deterministic calibration-derived parameter-state manifest and one
  write receipt under a caller-provided storage root;
- preserve calibration handoff, step, observation, and review identities as
  provenance;
- avoid external compatibility output, hardware write-back, rollback,
  calibration execution, GUI behavior, and shared parameter schema extraction.

The package exists to test whether storage can carry calibration provenance
without pretending it is adapter/legacy-source provenance.
