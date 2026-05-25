# Contract Primitives Candidate

This package is a narrow discovery implementation candidate, not accepted
Scopecat architecture.

It factors out repeated low-level contract checks that multiple late-discovery
composition and writer slices have started to duplicate:

- public-safe managed identifiers;
- syntax-only relative path checks;
- exact package primary-data paths;
- unique selected-measurement reference target lists;
- redacted display references;
- sha256 digest strings;
- package-root separation from measurement storage.

This slice deliberately does not define a measurement-record domain model,
final package schema, storage architecture, public API, GUI contract, or
runtime redaction engine. User-authored labels and reasons remain free text
unless a slice explicitly accepts a redaction policy surface.
