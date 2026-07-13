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
record, persist, or journal accepted values. The next integration step is an
executable closed domain invocation with correlated submission, fetch, and
reconciliation effects, not another quantum-package runtime abstraction.
Joint or variable-cardinality readout, a complete domain runtime protocol, and
a complete gate set are not yet provided.

See [`../../docs/quantum-domain-architecture.md`](../../docs/quantum-domain-architecture.md)
for the architectural boundary.
