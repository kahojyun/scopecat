# Scopecat Product and Architecture

The project charter is the product authority for current priorities. The other
documents describe the present architecture and its important semantics. They
are not a roadmap: implementation choices may change or be removed when a
simpler design better serves the workflows in the charter.

- [Project charter](project-charter.md): current product priorities, principles,
  and scope boundaries.
- [Experiment execution semantics](experiment-execution-model.md): current
  compiler, domain-lowering, effect, and logical-result design.
- [Lab daemon](lab-daemon.md): current durable ownership and client boundary.
- [Instrument authoring](instrument-control.md): the shared declaration, live
  control, symbolic-client, entity-mapping, and recording model.

Keep implementation architecture, package inventories, completed migration
plans, and current interface lists close to the code and tests that own them.
Use focused docstrings when an implementation decision needs local context.

Add another document here only when a cross-cutting design cannot be explained
clearly beside the code that owns it.
