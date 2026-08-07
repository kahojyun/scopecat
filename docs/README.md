# Scopecat Product and Architecture

The project charter is the product authority for current priorities. The other
documents describe the present architecture and its important semantics. They
are not a roadmap: implementation choices may change as demonstrated workflows
reveal a clearer or more scalable way to serve the charter.

- [Project charter](project-charter.md): current product priorities, principles,
  and scope boundaries.
- [Experiment execution semantics](experiment-execution-model.md): current
  compiler, domain-lowering, effect, and logical-result design.
- [Lab daemon](lab-daemon.md): current durable ownership and client boundary.
- [Instrument authoring](instrument-control.md): the shared declaration, live
  control, symbolic-client, entity-mapping, and recording model.
- [Measurement data workflows](measurement-data.md): recording intent, product
  grids and point clouds, repeat and traversal policy, invocation edits, ragged
  axes, notebook slicing and ecosystem exports, and schema-driven GUI
  visualization.
- [Adaptive experiments](adaptive-experiments.md): bounded, durable notebook
  loops whose next stage depends on earlier measurements.
- [Scalability benchmarks](scalability-benchmarks.md): current implementation
  boundaries, representative NISQ workloads, measurements, and target envelopes.

Keep implementation architecture, package inventories, completed migration
plans, and current interface lists close to the code and tests that own them.
Use focused docstrings when an implementation decision needs local context.

Add another document here only when a cross-cutting design cannot be explained
clearly beside the code that owns it.
