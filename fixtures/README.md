# Fixtures

Repository fixtures are durable operator/configuration inputs used by tests and
runnable examples. Compiler programs and runtime graphs are built transiently
from the user DSL and are intentionally not stored here.

## Owners

- `core/simple_scan`: public configuration inputs for the domain-neutral scan
  workflow used by preview, storage, config-registry, analysis, reporting,
  validation, authoring, and contract tests.
- `quantum/experiment_system`: demo quantum experiment-system fixture and
  runnable example input.

Core fixtures should stay domain-neutral. Quantum fixtures belong to the demo
support package and examples; reusable demo logic should live in
`examples/quantum/support`, while examples should wire fixtures into notebook
and script workflows.
