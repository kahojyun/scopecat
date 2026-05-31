# Prepared Run Scope Alignment Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow review projection across prepared-run parameter-state
consumption facts and setup-binding facts:

- consume one prepared-run parameter-state consumption summary;
- consume one setup-binding summary;
- compare prepared-run logical targets, parameter lineage target scope, selected
  setup binding sample/cooldown, and selected logical bindings;
- surface sample, target, binding, or selected-context mismatches as review
  findings;
- keep parameter write-back, hardware control, run start, fresh storage reads,
  catalog discovery, setup mutation, code execution, GUI behavior, and shared
  domain schemas out of scope.

The package exists to validate alignment pressure before a broader prepared-run
gate composes multiple context families.
