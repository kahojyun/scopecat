# Adapter-Authored Legacy Import Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable public API.

It tests the smallest normalized artifact boundary for old measurement records:
a user-owned adapter has already parsed a legacy system and emitted a
Scopecat-shaped manifest. Scopecat consumes the manifest facts without
supporting the legacy format directly.

The candidate:

- builds a structured summary from an adapter-authored import manifest;
- preserves adapter identity, external source identity, measurement identity,
  primary-data reference, declared preview metadata, linked-context references,
  and adapter findings;
- validates package-relative paths and declared preview consistency;
- keeps legacy parsing, LabRAD/DataVault/Labber reader behavior, storage
  mutation, import acceptance, schema inference, package integrity, recursive
  relation traversal, GUI behavior, and stable SDK/API design out of scope.

The fixture is synthetic and public-safe. Local legacy samples may inform the
pressure behind the manifest shape, but the implementation candidate must not
depend on or parse those legacy sources.
