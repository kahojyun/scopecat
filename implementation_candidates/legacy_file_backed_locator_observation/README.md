# Legacy File-Backed Locator Observation Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow file-level observation boundary for brownfield sidecar
workflows:

- consume an already-built legacy sidecar post-run review summary;
- select one declared, available, redacted `legacy_path` locator;
- observe a caller-provided relative path under a caller-provided external
  root;
- compare optional declared sha256 and byte-size facts.

The candidate intentionally does not query a legacy backend, parse legacy data,
verify previews, import data, mutate storage, repair references, write
parameters, decide measurement validity, or define GUI behavior.
