# Fixtures

Repository fixtures are durable input records used by tests and runnable
examples. They are not hidden architecture definitions.

## Owners

- `core/simple_scan`: public core model and workflow used by preview,
  storage, config-registry, analysis, reporting, validation, authoring, and
  contract tests.
- `quantum/experiment_system`: demo quantum experiment-system fixture and
  runnable example input.

Core fixtures should stay domain-neutral. Quantum fixtures belong to the demo
support package and examples; reusable demo logic should live in
`examples/quantum/support`, while examples should wire fixtures into notebook
and script workflows.
