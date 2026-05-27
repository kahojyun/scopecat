# Reference-Only Source Observation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable import API.

The candidate performs file-level observation for reviewed reference-only
legacy import facts. It starts after reference-only import has preserved a
lab-managed external source reference, then checks one explicit source path
under a caller-provided external root.

The candidate:

- validates the consumed reviewed reference-only import facts;
- requires an explicit file-level observation request;
- validates continuity with the preserved external reference;
- observes file availability, sha256, and byte size;
- returns review findings for unavailable or mismatched file facts;
- keeps declared preview metadata as an adapter assertion, not an observed
  preview contract.

It deliberately does not parse legacy formats, count rows, infer schemas,
verify preview metadata, plot data, expose dataframe-like rows, repair moved
references, copy primary data, mutate storage, import linked-context payloads,
or define GUI behavior.

This prototype assumes the caller-provided external root is not concurrently
mutated during observation. It rejects symlink roots, parents, and targets
during normal operation, but does not claim adversarial filesystem race safety.
