# Parameter Trusted Drift Projection Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for a narrow parameter-state drift
projection slice:

- build a structured trusted-history summary from explicit fixture input;
- keep the builder side-effect free;
- include only declared trusted scalar entries from eligible committed
  parameter states;
- report excluded seed or exploratory states;
- report skipped untrusted or non-scalar entries as review findings;
- avoid rendered plots, schema migration, hardware write-back, instrument
  state tracking, rollback automation, shared domain models, or GUI behavior.

The package exists to test whether accepted parameter states can support a
trusted drift/history projection without treating copied seed values,
exploratory states, or table-shaped parameters as calibrated truth.
