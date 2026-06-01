# Calibration Step Proposed Write Link Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow calibration workflow boundary:

- a calibration step record may reference reviewable proposed parameter writes;
- proposed writes can target a parameter-state lineage and path;
- proposed writes can summarize before/after candidate values;
- review state is distinct from apply state;
- accepted or rejected review states still do not apply writes in this slice.

The candidate is side-effect free. It does not read measurement payloads,
execute calibration code, fit data, decide continuation, write parameter
stores, emit compatibility output, roll back writes, schedule work, or control
hardware.
