# Architecture

These documents explain the present implementation to Scopecat contributors:

- [Experiment execution semantics](execution.md) covers authoring ownership,
  specialization, domain lowering, effects, completion, and evidence.
- [Lab daemon](daemon.md) covers durable run ownership, instrument workers,
  cancellation, API events, configuration, and storage.
- [Scalability benchmarks](../scalability.md) records representative workload
  profiles, target envelopes, and current boundaries.

Architecture is an implementation choice rather than a product requirement.
Change it decisively when demonstrated workflows reveal a clearer design, while
preserving user-facing concepts that still deliver value.
