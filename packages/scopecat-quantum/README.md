# Scopecat Quantum

Hardware-independent quantum domain building blocks for Scopecat.

This package owns immutable gate, circuit, pulse, schedule, calibration, and
target-adapter contracts. It does not own experiment templates, laboratory
calibration values, physical wiring, concrete AWG or digitizer artifacts,
instrument runtimes, or response models. Those belong to the laboratory
package that consumes `scopecat` and `scopecat-quantum`.

The initial package is deliberately small. It supports checked gate/circuit
composition, logical pulse programs, canonical scheduling, exact data-only gate
and measurement calibration selection, hygienic circuit-to-pulse lowering with
structured event and acquisition provenance, and hardware-neutral target
compiler protocols. A measurement calibration emits readout stimulus plus one
acquisition and preserves the exact result slot declared by the circuit.
Prepared circuit-target entries and batches retain every intermediate proof
while deriving target requests whose event and acquisition identities are
qualified by semantic entry identity. A pure result-mapping proof can bind
those entry-qualified acquisition addresses to Scopecat logical points and
product-use occurrences before any target effect, and a
`CompiledCircuitTarget` can bind the resulting mapping to the exact checked
artifact. The quantum package deliberately does not choose product-value
acceptance policy. The laboratory demo binds each result address explicitly
with `integrated_iq_shots(...)` or `raw_trace_shots(...)`, then seals exact
mixed coverage with
`select_fake_measurement_realization(compiled_target, target, bindings)` and
executes the resulting heterogeneous batch once through
`execute_realized_fake_measurements`. The exact laboratory-owned
`FakeListTarget` must match target identity and capability fingerprint; its
sample rate must match the artifact, and its acquisition-channel binding must
match each compiled window. The remaining pre-effect proof checks the prepared
acquisition against that window, including entry, program, event, signal, kind,
start, and sample-count facts, before accepting `[shot]` or `[shot, sample]`
product shapes through core's quantum-neutral value closure. It does not reduce,
record, or persist accepted values. Core now provides a quantum-neutral closed
invocation and correlated submit/fetch/reconcile ABI; the laboratory demo—not
this package—adapts the fake hardware primitive to that boundary, including
idempotent job identity, sealed submission states, and journaled host effects.
This package remains free of laboratory runtime and job-store policy. Core and
the laboratory demo now carry accepted domain values through producer-neutral
assembly and independent record projection, then commit one receipt-bearing
record per logical point. Recording receipts and journal evidence retain hashes,
references, and logical point identity without importing quantum addresses or
raw frames. Dataset compaction, manifest publication, and terminal run outcomes
remain core/laboratory integration work rather than quantum-package concerns.
The package now also supplies a host-only binary integrated-IQ discriminator
semantic contract, a typed point-local IQ-shot-to-probability transform builder,
and a pure reference host implementation. Its two finite, distinct centroids and
explicit nearest-centroid tie policy are semantic parameters. Numerical
precision and rounding are not yet specified, so this contract does not claim
cross-realization or offloaded equivalence. Joint or variable-cardinality
readout, offloaded transform proofs, `POINT_SET` execution, authoring DSL
integration, local-source binding and engine migration, cross-point analysis,
polling, chunking, cancellation, a cross-process job store, and a complete gate
set are not yet provided. The initial reference implementation executes
point-local transforms on the host only.

See [`../../docs/quantum-domain-architecture.md`](../../docs/quantum-domain-architecture.md)
for the architectural boundary.
