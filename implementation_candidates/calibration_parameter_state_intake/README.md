# Calibration Parameter-State Intake Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow parameter-state-owned intake boundary after calibration has
accepted a proposed write for handoff:

- validate the nested calibration accepted-write handoff input;
- accept only a ready handoff request through explicit parameter-state review;
- project a managed parameter-state summary with the accepted handoff diff
  applied to the base state entries;
- preserve calibration step, observation, proposed-write, and handoff
  identities as provenance;
- avoid storage mutation, durable history writes, compatibility output,
  hardware write-back, calibration execution, rollback, GUI behavior, and
  shared parameter schema extraction.

The package exists to test the integration point between calibration review and
parameter-state management without making calibration the parameter-state
authority.
