# Fixtures

Repository fixtures are durable input records used by tests and runnable
examples. They are not hidden architecture definitions.

## Owners

- `core/simple_scan`: minimal core model fixture used by low-level model,
  validation, and authoring tests.
- `core/simulated_scan`: public core workflow sample used by dry-run, storage,
  config-registry, analysis, reporting, runner-adapter, and
  contract tests.
- `quantum/readout_frequency_calibration`: demo readout-frequency support
  package fixture and runnable example input.
- `quantum/readout_iq_quality`: demo readout-IQ support package fixture and
  runnable example input.
- `quantum/sample_templates`: demo sample-template fixture and native example
  input.

Core fixtures should stay domain-neutral. Quantum fixtures belong to the demo
support package and examples; reusable demo logic should live in
`examples/quantum/support`, while examples should wire fixtures into notebook
and script workflows.
