# Legacy Evidence Receipt Read View Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow read-only view:

- read an existing measurement-record manifest from a declared path;
- read explicitly declared legacy review-evidence receipt paths;
- surface receipt identity, source intent, locator-observation evidence, and
  receipt findings;
- classify missing or malformed receipts as review findings.

The candidate intentionally does not scan storage, read primary data, import
legacy payloads, parse legacy primary data, verify previews, repair
references, mutate storage, write parameters, decide measurement validity, or
define GUI behavior.
