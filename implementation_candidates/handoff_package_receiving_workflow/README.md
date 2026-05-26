# Handoff Package Receiving Workflow Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a final import API, GUI workflow, archive format, signature
scheme, dataframe adapter, or storage schema.

It composes existing receiving-side handoff package candidates into one local
workflow:

- inspect an existing directory-shaped package through the read-only
  inspection workflow;
- observe package-local integrity through the read-only integrity observation
  candidate;
- require explicit approval and reviewed package/preview/integrity continuity;
- require `declared_integrity_verified` before storage acceptance;
- preflight package, storage, and the local artifact target before writing the
  inspection artifact or accepting storage;
- accept the package into new local storage records by delegating to the
  existing acceptance candidate.

The slice intentionally stays as composition. It does not add new package
parsing, write linked-context payloads, extract archives, validate signatures,
define GUI state, define dataframe behavior, update existing records, or
promote a final storage or measurement-record schema.
It also assumes the package root is not concurrently modified between
inspection, integrity observation, and acceptance.
