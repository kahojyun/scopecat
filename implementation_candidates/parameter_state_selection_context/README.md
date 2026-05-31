# Parameter State Selection Context Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for a narrow parameter-state selection
context slice:

- build a structured summary from explicit fixture input;
- keep the builder side-effect free;
- represent parameter-state selection as a context input reference;
- carry scenario-specific intent labels without making them lifecycle
  semantics;
- validate context requirements such as committed/trusted selected state when
  declared by the fixture;
- avoid hardware write-back, current instrument-state claims, rollback
  mutation, branch/tag/commit semantics, shared domain models, or GUI behavior.

The package exists to test whether a previous committed parameter state can be
selected for a future context without turning that selection into hardware
rollback or a special known-good model.
