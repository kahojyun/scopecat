# Calibration Accepted Write Handoff Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- an accepted calibration proposed write can be prepared as input to parameter
  state management;
- the handoff names the base parameter-state snapshot, lineage, parameter path,
  and proposed diff;
- the handoff can shape a draft/review request for the parameter-state route;
- acceptance for handoff is distinct from parameter-state commit, compatibility
  output, and hardware apply.

The candidate is side-effect free. It does not create parameter-state drafts,
commit parameter states, write compatibility files, apply hardware writes,
read measurement payloads, execute fitting, schedule work, or define rollback.
