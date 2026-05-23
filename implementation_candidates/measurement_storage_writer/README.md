# Measurement Storage Writer Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

The candidate performs a tightly bounded filesystem mutation: it writes one new
measurement record directory under a caller-provided storage root from declared
append chunk files. It preflights declared sha256 and size facts before writing
anything, refuses existing targets, and writes deterministic record metadata.

It deliberately does not control hardware, infer schemas, parse source data
semantics, define a final storage model, stream live events, accept imports,
write export packages, or define GUI behavior.
