# Context Inclusion Semantics Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow prepared-run context-inclusion contract:

- `include_state=selected` with a `context_id` records the referenced context;
- `required` controls absence severity, not whether selected context is
  recorded;
- optional selected context is still recorded;
- unavailable required context produces review findings;
- unavailable optional context and optional-not-selected context remain
  informational;
- requirement source stays local to the prepared-run/template policy that made
  absence significant.

The package deliberately does not define a universal context schema, template
language, GUI workflow, run blocking contract, storage model, hardware control,
parameter write-back, environment sync, code execution, or migration plan.
