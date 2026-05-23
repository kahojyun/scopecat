# Measurement Source Observation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

The candidate performs a bounded read-only observation of one declared primary
data file under a caller-provided storage root. It validates explicit
sha256, size, and row-count expectations for that file and returns review
findings when the file is unavailable or differs from the declared facts.

It deliberately does not mutate storage, infer schemas, accept imports, write
export packages, repair files, scan storage roots, control hardware, stream
live events, or define GUI behavior.
