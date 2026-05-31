# Adapter-Authored Parameter State Import Preview Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable public API.

It tests the smallest normalized artifact boundary for legacy parameter
sources: a user-owned adapter has already parsed old parameter files, tables,
or project-specific outputs and emitted a Scopecat-shaped manifest. Scopecat
consumes the manifest facts without supporting the legacy formats directly.

The candidate:

- builds a structured import-preview summary from an adapter-authored
  parameter-state manifest;
- preserves adapter identity, declared legacy source references, candidate
  state metadata, normalized candidate entries, skipped entries, and adapter
  findings;
- validates public-safe/redacted source displays and declared source formats;
- validates candidate entry paths, trust states, value shapes, and source
  references;
- keeps legacy JSON/XLSX parsing, stable adapter API design, import
  acceptance, managed parameter-state creation, schema migration, external
  file authority, hardware write-back, GUI behavior, and shared domain models
  out of scope.

The fixture is synthetic and public-safe. Local legacy samples may inform the
pressure behind the manifest shape, but the implementation candidate must not
depend on or parse those legacy sources.
