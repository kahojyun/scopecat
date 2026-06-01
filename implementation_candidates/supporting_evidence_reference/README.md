# Supporting Evidence Reference Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow reference-only boundary for user-supplied supporting
evidence:

- summarize explicitly supplied debug, audit, handoff, or review-evidence
  references;
- distinguish `attachment`, `artifact`, and `unspecified` as label-only
  evidence kinds, without requiring artifact provenance in the base route;
- require an explicit lifecycle posture so pre-run, during-run, post-run, and
  handoff evidence do not blur together;
- relate evidence to measurement, running-measurement, prepared-run,
  operator-approval, parameter-state, or calibration-step targets;
- keep evidence as supporting review material rather than primary measurement
  data, canonical context, run-start input, or a second parameter authority;
- surface unavailable evidence or target references as review findings;
- avoid payload import, file observation, evidence parsing, checksum
  validation, storage mutation, external file authority, preview generation,
  recursive relation traversal, artifact-provenance validation,
  measurement-validity claims, GUI behavior, or shared attachment schema
  extraction.
