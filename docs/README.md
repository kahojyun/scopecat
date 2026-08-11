# Scopecat documentation

The [project charter](project-charter.md) is the authority for current product
priorities and scope. Start with the task guide that matches the work; compiler,
daemon, and scalability details are developer architecture rather than concepts
an experiment author must learn first.

## User task guides

- [Experiment authoring dataflow](experiment-authoring.md): scalar and array
  shape, availability-based compute placement, point plans, return-as-record,
  and complete-path acceptance.
- [Instrument control and authoring](instrument-control.md): live and symbolic
  clients, physical routing, shared state, and capability extension.
- [Measurement data workflows](measurement-data.md): recorded schema, ragged
  arrays, notebook selection, ecosystem projection, bounded Arrow reading, and
  schema-driven GUI behavior.
- [Analysis publication](analysis-publication.md): the durable output ontology,
  stable identities, lossless conversion boundary, and deliberate separation
  from dataframe libraries and workflow execution.

## Developer architecture

- [Experiment execution semantics](experiment-execution-model.md): compiler,
  domain-lowering, effect, and logical-result design.
- [Lab daemon](lab-daemon.md): durable ownership and client boundary.
- [Scalability benchmarks](scalability-benchmarks.md): current implementation
  boundaries, representative NISQ workloads, measurements, and target envelopes.

These documents describe the present system, not a roadmap. Implementation may
change as demonstrated workflows reveal a clearer or more scalable way to serve
the charter.

## Documentation ownership

Keep implementation architecture, package inventories, completed migration
plans, and current interface lists close to the code and tests that own them.
Use focused docstrings when an implementation decision needs local context.

Add another document here only when a cross-cutting design cannot be explained
clearly beside the code that owns it.
