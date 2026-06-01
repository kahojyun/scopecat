# Calibration-Derived Parameter State Measurement Context Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow route-level composition boundary:

- a calibration observation can remain linked to the measurement record it used;
- an accepted calibration write handoff can feed parameter-state intake;
- the resulting managed parameter-state snapshot can be stored/read;
- a later prepared run can select that snapshot as parameter context;
- the later measurement record can link the same selected snapshot as actual
  run-start context.

The candidate is side-effect free. It does not read measurement payloads,
execute fitting or calibration code, start runs, control hardware, write
parameters, produce compatibility outputs, mutate storage, traverse a relation
graph, or define shared calibration, parameter-state, prepared-run, or
measurement schemas.
