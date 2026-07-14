# Scopecat Quantum

Hardware-independent quantum domain building blocks for Scopecat.

This package owns immutable gate, circuit, pulse, schedule, calibration, and
target-adapter contracts. It does not own experiment templates, laboratory
calibration values, physical wiring, concrete AWG or digitizer artifacts,
instrument runtimes, or response models. Those belong to the laboratory
package that consumes `scopecat` and `scopecat-quantum`.

The `scopecat_quantum.authoring` facade provides opaque logical-qubit,
scalar-input, circuit, and measurement-result handles. Symbolic gate arguments
and repeat counts are closed with `bind_circuit`, which returns the existing
verified circuit IR used by calibration and target passes:

```python
from scopecat_quantum import authoring
from scopecat_quantum import GateParameterKind

q0 = authoring.qubit("q0")
x_count = authoring.scalar_input("x_count", GateParameterKind.INTEGER)
x = authoring.single_qubit_gate("x")
readout = authoring.measure(q0, result="raw_iq")
program = authoring.circuit(
    "x-count",
    authoring.sequence(authoring.repeat(x(q0), x_count), readout),
)
bound = authoring.bind_circuit(program, {"x_count": 3})
```

`circuit_domain_program` and `circuit_domain_call` project those typed handles
onto core's explicit domain-program seam. Because the current laboratory
reference also declares two host-derived probability products, it temporarily
uses a generic composite declaration on that same seam; its authored `Circuit`
body is still the target compiler's source of truth.

The initial package is deliberately small. It supports checked gate/circuit
composition, logical pulse programs, canonical scheduling, exact data-only gate
and measurement calibration selection, hygienic circuit-to-pulse lowering with
structured event and acquisition provenance, and hardware-neutral target
compiler protocols. A measurement calibration emits readout stimulus plus one
acquisition and preserves the exact result slot declared by the circuit.
Prepared circuit-target entries and batches retain every intermediate proof
while deriving target requests whose event and acquisition identities are
qualified by semantic entry identity. Adapter selection returns a
`DomainExecutionOffer`; after backend batching, the resulting
`DomainBatchContext` supplies scoped `DomainPointRef` and
`DomainProductUseRef` values. The adapter calls `context.new_preparation()`,
and the quantum result mapper uses that SDK builder to bind target entries and
entry-qualified acquisitions without exposing materialized compiler plans.
One physical acquisition may fan out to several demanded uses of the same
logical product while every direct use remains exactly covered. A
`CompiledCircuitTarget` can bind the resulting `DomainResultMapping` to the
exact checked artifact. The quantum package deliberately does not choose
product-value acceptance policy. The laboratory demo binds each result address
explicitly with `integrated_iq_shots(...)` or `raw_trace_shots(...)`, then seals
exact mixed coverage with
`select_fake_measurement_realization(compiled_target, target, bindings)` and
executes the resulting heterogeneous batch once through
`execute_realized_fake_measurements`. The exact laboratory-owned
`FakeListTarget` must match target identity and capability fingerprint; its
sample rate must match the artifact, and its acquisition-channel binding must
match each compiled window. The remaining pre-effect proof checks the prepared
acquisition against that window, including entry, program, event, signal, kind,
start, and sample-count facts, before accepting `[shot]` or `[shot, sample]`
product shapes through core's quantum-neutral value closure. It does not reduce,
record, or persist accepted values. Core now provides a declarative laboratory
job boundary: the demo supplies `DomainInvocationSpec`,
`DomainTargetArtifactIdentity`, `DomainResourceClaim`, and a `DomainRuntime`
whose methods receive only core-minted request values. The demo—not this
package—adapts the fake hardware primitive to that boundary. Core alone owns
idempotent submission identities, sealed durable states, orchestration, and
journaled host effects.
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
cross-realization or offloaded equivalence. The laboratory demo now declares
result mapping, point-local host transforms, invocation identity and payload,
runtime requests, result realization, and resources entirely through the
public domain SDK. The builder lowers value fragments, transform graphs, and
closed invocation proofs internally; core owns record projection as an
independent global selection. Laboratory packages do not receive those native
objects. Joint or variable-cardinality readout, authored
host-transform dependency edges, offloaded transform proofs, `POINT_SET`
execution, local-source binding and engine migration, cross-point analysis,
polling, chunking, cancellation, a cross-process job store, and a complete gate
set are not yet provided. The initial reference implementation executes
point-local transforms on the host only.

See [`../../docs/quantum-domain-architecture.md`](../../docs/quantum-domain-architecture.md)
for the architectural boundary.
