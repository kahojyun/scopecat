# Calibration Review Action Recording Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow review-action recording boundary:

- consume a calibration continuation review surface;
- validate user-declared action events against labels exposed by that surface;
- record actor, timestamp, target, action label, and reason;
- keep each event as review/audit intent only.

The candidate does not execute actions, render a GUI, run notebook cells, read
measurement payloads, run fitting or calibration, control hardware, write
parameters, start runs, mutate storage, or define a shared action schema.
