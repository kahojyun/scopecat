# Setup Binding Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first setup-binding slice:

- build a structured setup-binding summary from explicit fixture input;
- keep the builder side-effect free;
- validate that setup binding references station registry context explicitly;
- summarize sample/cooldown/session-specific binding snapshots;
- keep user/project-defined inner payloads opaque by default;
- carry declared generated line/readout views without executing project
  generator or converter code;
- report binding changes as review attention without claiming parameter
  invalidation;
- avoid hardware control, station management, parameter mutation, payload
  interpretation, generator execution, shared snapshot contracts, or GUI
  behavior.

The package exists to test whether setup binding can move from fixture-only
validation to a narrow implementation-shaped boundary while remaining separate
from parameter state, station registry authority, and hardware control.
