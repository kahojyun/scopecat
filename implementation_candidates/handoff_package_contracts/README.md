# Handoff Package Route Contracts

This candidate-local support module holds validation that is already shared by
the handoff package route: writer input, package manifest preview, opener
preflight, and the composition slice that connects them.

It is not the final product data model. Slice-local code still owns policy,
file-system effects, source observation, storage mutation, and continuity
checks. The shared helpers cover only stable route contracts:

- managed handoff package identity fields
- manifest item state/include/reason shape
- selected primary-data package path topology
- canonical primary-data default-bundle entry
- preview-ready column, axis, and plot binding

Free-text labels remain free text. These helpers enforce public-safe managed
references and redacted display-reference shapes for handoff package outputs;
they do not define a general runtime redaction policy.
