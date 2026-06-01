# Reviewed Legacy Sidecar Evidence Append Receipt Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow storage mutation:

- consume an approved reviewed legacy sidecar append intent;
- preflight an existing measurement-record directory and manifest identity;
- use a record-local lock guard;
- write one no-overwrite review-evidence receipt under the existing record.

The candidate intentionally does not import primary data, parse legacy data,
verify previews, repair references, write parameters, decide measurement
validity, replace manifests, refresh read models, or define GUI behavior.
