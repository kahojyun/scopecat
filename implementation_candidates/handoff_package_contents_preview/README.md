# Handoff Package Contents Preview Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first receiving-side
Scopecat-authored handoff package preview slice:

- build a structured summary from an explicit Scopecat export manifest;
- keep the builder side-effect free;
- support the first step of the open-before-import receiving flow by previewing
  package contents before read-only package use or later acceptance;
- require non-empty selected measurements and preserve selected measurements,
  primary-data references, declared preview metadata, attachments, artifacts,
  and linked context;
- report degraded preview metadata, missing context, and visible references
  that are not packaged as review findings.

The package exists to test whether Scopecat can summarize what a
Scopecat-authored handoff package says it contains before read-only package use
or local storage import. It keeps package preview manifest-only and separate
from archive extraction, file reads, checksum validation, storage mutation,
import acceptance, schema inference, recursive relation traversal, GUI
behavior, and shared measurement schema.

Stable route-level checks that are already shared with writer/composition work
are delegated to `../handoff_package_contracts/`. Slice-local code still owns
the manifest-only preview policy, degraded-preview handling, package-content
classification, and review findings.

The read-only package opener is validated separately in
`../handoff_package_opener/`. Future SDK or GUI-shaped surfaces may wrap that
behavior to inspect a standalone package, load declared primary data, and use
declared preview metadata without requiring local storage import first.
