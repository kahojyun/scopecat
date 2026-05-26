# Handoff Package Acceptance Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, final storage layout, stable import API, or package format.

It tests the first approved receiving-side mutation intended to run after a
user has opened and reviewed a directory-shaped handoff package. This
candidate verifies approval plus reviewed package identity/classification; it
does not bind to an inspection receipt.

- require an explicit acceptance request with an approved review state;
- reopen the package through the read-only handoff package read view;
- require the reviewed package identity and preview classification to match;
- require this first slice to select every package measurement;
- copy package-local primary CSVs into new local record directories;
- write deterministic candidate-local record manifests next to the copied
  primary data;
- preserve linked context as reference-only facts;
- refuse existing record directories and storage targets;
- roll back ordinary partial writes.

The slice intentionally keeps the acceptance boundary narrow. It does not
extract archives, recursively import linked context, validate package checksums
or signatures, infer schemas or scalar types, add dataframe behavior, define a
GUI workflow, accept existing-record updates, or promote a final storage
schema. It also assumes the package root is not concurrently modified while
acceptance is running.
