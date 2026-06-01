# Legacy Locator Observation Review Bundle Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow local review composition:

- consume an already-built legacy sidecar post-run review summary;
- consume zero or more prior legacy file-backed locator observation summaries;
- surface observed, unavailable, and file-fact-mismatch locator states;
- preserve declared preview metadata as unverified by file-level observation.

The candidate intentionally does not perform fresh file observation, query
legacy backends, parse legacy data, verify previews, accept imports, mutate
storage, repair references, write parameters, decide measurement validity, or
define GUI behavior.
