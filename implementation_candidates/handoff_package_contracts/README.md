# Handoff Package Route Contracts

This candidate-local support module holds validation used to keep the handoff
package route consistent across writer input, package manifest preview, opener
preflight, and composition work.

It is not the final product data model. Slice-local code still owns policy,
file-system effects, source observation, and storage mutation. Most helpers
cover stable route contracts already used by multiple slices:

- managed handoff package identity fields
- manifest item state/include/reason shape
- selected primary-data package path topology
- canonical primary-data default-bundle entry
- preview-ready column, axis, and plot binding

Receiving-side composition currently also uses provisional route helpers for:

- receiving workflow separation for package, storage, and local review artifact
  output targets
- reviewed package, preview, and integrity continuity facts across composed
  receiving-side observations

Free-text labels remain free text. These helpers enforce public-safe managed
references and redacted display-reference shapes for handoff package outputs;
they do not define a general runtime redaction policy.
