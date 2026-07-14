# Quantum Domain Package Architecture

Status: implemented baseline; accepted direction for remaining slices

`scopecat-quantum` is the hardware-independent quantum domain building-block
package for Scopecat. It owns quantum semantics and checked lowering contracts;
it does not own a laboratory's instruments, wiring, calibration data, runtime
provider, or experiment catalog.

The current package dependency direction is one way:

```text
scopecat-quantum ---> scopecat
scopecat          -X-> scopecat-quantum
```

`quantum-lab-demo` depends on both packages and supplies the first concrete
laboratory target. The dependency remains one way: neither core nor the
hardware-independent quantum package imports the laboratory adapter.

## Layering

The domain pipeline has distinct transient representations:

```text
Gate/Circuit IR
      |
      | exact calibration selection
      v
CalibrationSelection
      |
      | checked hygienic circuit-to-pulse lowering
      v
Pulse authoring IR
      |
      | verification and scheduling
      v
Scheduled Pulse IR
      |
      | entry-qualified batch preparation
      v
Prepared circuit target batch
      +------------------------------+
      | laboratory target compiler   | exact SDK-ref result mapping
      v                              v
Target artifact             CircuitTargetResultMapping
```

Gate/Circuit IR contains logical operands, gate semantics, typed arguments,
measurement declarations, and sequence/parallel composition. It contains no
physical channel, waveform sample, sample rate, compiler identity, product
identity, or record policy. Gate definitions and calls are separate.
Measurement is not modeled as a unitary gate; it defines a domain acquisition
slot that an integration adapter may later map to a Scopecat product use.

Pulse authoring IR contains logical drive, readout, flux, and acquisition
signals plus analytic envelopes and structural sequence/parallel composition.
Scheduling produces a canonical timeline in exact decimal SI seconds; binary
floating-point or device sample-grid quantization belongs to the target
compiler. Neither representation contains an AWG list index, physical channel,
waveform-memory address, trigger line, quantized sample format, or device
command.

Calibration declarations are split into typed gate and measurement families.
Gate calibrations relate an exact gate-call contract to a reusable pulse
template. Measurement calibrations relate `(qubit, acquisition_kind)` to a
readout template that declares exactly one acquisition slot, contains exactly
one matching acquisition event, and plays the measured qubit's readout signal.
The aggregate `CalibrationCatalog` and `CalibrationSelection` prove complete
coverage across both families while preserving their distinct keys and
bindings. Calibration templates carry template-relative structural identities;
operation and result-slot identities belong to individual circuit occurrences
and are introduced only by selection and lowering. The first implementation
supports only exact, data-only calibration keys; parameterized templates and
rewrite systems must extend that contract rather than make circuit operations
carry calibrated amplitude, duration, or frequency.

`lower_circuit_to_pulses` consumes a `VerifiedCircuitProgram` and its exact
`CalibrationSelection`. It maps circuit sequence and parallel nodes
homomorphically, prefixes every template event identity with structural circuit
and operation scopes, and returns a sealed `LoweredCircuitPulseProgram`. A gate
produces a `GatePulseInstantiation`. A measurement produces a
`MeasurementPulseInstantiation`, rewrites the template-local slot to the exact
slot declared by `Measure`, and emits both readout stimulus and acquisition.
The result exports typed provenance for every pulse leaf plus the exact
template-to-circuit mapping for every acquisition slot. This preserves
intermediate origin facts for target compilation, hardware offload,
diagnostics, and later domain-program correlation without embedding
calibration metadata into Pulse IR itself.

The lowering proof deliberately stops before scheduling. A circuit's
qubit-disjoint parallel proof does not imply that selected templates avoid a
shared coupler or spectator signal. The independent scheduling pass continues
to own time normalization, acquisition closure, and cross-template logical
signal overlap checks.

Target compiler protocols consume only canonical scheduled pulse programs.
They expose target, compiler, artifact, capability-fingerprint, entry, and
finite-repetition identities without defining a universal hardware schema.
Concrete artifacts and device limits remain owned by the target adapter.
Artifacts are logically immutable by adapter contract, and their fingerprint
must cover their opaque payload. The foundational package can check provenance
metadata when a trusted in-process compiler returns; it cannot independently
interpret or prove target-owned payload contents.

Circuit-derived target work retains a separate sealed batch sidecar. Each
prepared entry exports its verified circuit, calibration selection, lowered
pulse program, canonical schedule, and exact provenance under one
`TargetCompileEntryId`. Event and acquisition identities become target-work
addresses only when paired with that entry identity. A
`PreparedCircuitTargetBatch` proves exact ordered coverage and derives the
ordinary `TargetCompileRequest`; the target compiler still sees only scheduled
Pulse IR. Reusing the same circuit, template event, or acquisition slot in
several entries is therefore safe without manufacturing globally unique
domain identities.

The batch also feeds a separate pure result-mapping boundary. After adapter
selection and backend batching, core creates a `DomainBatchContext` containing
only SDK-owned `DomainPointRef` and `DomainProductUseRef` capabilities for that
exact call and point batch. The adapter obtains a context-bound
`DomainPreparationBuilder` through `context.new_preparation()`.
`seal_circuit_target_result_mapping` translates the quantum batch into the
builder's `map_measurements` declarations and retains the returned
`DomainResultMapping` inside `CircuitTargetResultMapping`. Target entries bind
bijectively to SDK point references, and entry-qualified acquisition addresses
bind to SDK product-use references. One physical acquisition may fan out to
several demanded uses of the same logical product, including a compiler-minted
input use for an unrecorded authored transform; every context-selected source
use must still be covered exactly once. The context-bound builder owns the
internal closure, so the quantum public boundary exposes neither
`MaterializedLinkedPointSet` nor compiler point/product-use identities. Adapter
ordering is retained as provenance but cannot replace canonical logical output
order. Record aliases remain downstream projections and do not create
acquisition work.

`CompiledCircuitTarget` closes the next pure edge: the checked target artifact
must retain the exact mapped batch request, target/compiler/capability identity,
ordered entry coverage, repetition count, artifact identity, and artifact
fingerprint. This still is not execution or result acceptance; it only prevents
a compiled artifact from being paired with another logical mapping. Equal
reconstructed fake artifacts correlate by checked content identity rather than
Python object identity.

## Composition Rules

- sequence and parallel blocks compose within one IR layer;
- parallel circuit branches may not share logical qubits;
- scheduled intervals may not overlap on one logical signal unless a future
  operation defines an explicit merge semantic;
- acquisition slots are declarations and must close against exactly one
  acquisition event;
- gates enter Pulse IR only through checked calibration/decomposition lowering;
- target compilation cannot consume unscheduled Pulse IR;
- target-batch event and result addresses are `(entry_id, event_id)` and
  `(entry_id, acquisition_slot_id)`, never physical list or segment indexes;
- one context-bound result mapping binds each target entry to one SDK point
  reference and each acquisition address to one or more SDK product-use
  references while covering every core-selected source use exactly once;
- one compiled-circuit proof binds an artifact to that exact batch and mapping;
- repeated target frames are correlated by explicit shot identity and remain
  raw evidence until a separate output-realization contract accepts them;
- the demo assigns every mapped result address an explicit
  `integrated_iq_shots(...)` or `raw_trace_shots(...)` binding, and
  `select_fake_measurement_realization(compiled_target, target, bindings)`
  requires the exact `FakeListTarget` and seals exact coverage before
  execution;
  policies compose freely across addresses in one batch, subject to each
  result's product, prepared acquisition, and compiled-window contracts;
- Scopecat scans, products, record projections, and experiment templates remain
  outside quantum program bodies.

Composition and canonicalization are semantic. Reassociating nested sequences,
permuting independent parallel branches, reordering gate or calibration
catalogs, or changing target artifact storage order must not change observable
intent.

Pulse event and acquisition-slot identities are structural `(scope, local_id)`
values. Calibration templates may use relative scopes for internal composition;
circuit-to-pulse lowering preserves event scopes beneath structural circuit and
operation prefixes. The familiar path-like `qualified_name` is only an
injective rendered form with segment-wise escaping. Directly concatenating
reusable calibration programs or manufacturing globally unique strings is not
a valid lowering strategy. The template's acquisition slot is similarly local:
measurement lowering substitutes the circuit-declared slot rather than leaking,
prefixing, or manufacturing a result identity. Typed circuit, operation,
calibration, template-event, and template-slot identities remain in the
lowering provenance sidecar instead of coupling lower Pulse IR back to the
higher Circuit IR.

Verified, selected, lowered, scheduled, prepared, mapped, and compiled wrappers
are immutable trusted-process stage values. The corresponding
verify/select/lower/schedule/prepare/compile/bind operation establishes each
stage's invariants once; later pure stages rely on its nominal type and frozen
state instead of construction secrets, same-process tamper detection, or
rerunning earlier transformations. A bind still checks independent facts such
as mapping-to-request correlation. Plugins, deserialized values, provider
responses, and process-boundary inputs remain validation boundaries and must be
checked before a new trusted stage value or accepted runtime result is issued.

## Laboratory Boundary

The demo package is the first laboratory consumer. It owns concrete qubit and
coupler wiring, channel and clock/trigger topology, calibration values, fake
AWG/digitizer capabilities, list compiler and artifact, response model,
instrument runtime, experiments, and analysis.

A fake list-mode AWG plus segmented digitizer is therefore not built into
`scopecat-quantum`. It implements the package's target contracts in
`quantum-lab-demo`. If that implementation later becomes useful to several
independent laboratories, it may move to a separate
`scopecat-quantum-fake-target` distribution.

The first target slice compiles ordered quantum target entries to AWG list
entries, loops the complete list for a finite shot count, and maps every
digitizer frame explicitly back to target entry, shot, and acquisition slot.
The prepared circuit-target batch resolves that entry-qualified slot address
back to exact circuit, measurement, calibration, and template provenance. The
pure circuit-target result adapter binds already-proven entry identities to
context-owned point references and proven result addresses to context-owned
product-use references. Several uses of one logical product may share a single
physical acquisition without duplicating target work. Physical list and
segment indices never replace either logical identity.
After synchronous fake execution, the laboratory adapter revalidates the raw
run against the compiled artifact and produces a `CorrelatedFakeListRun` in
canonical logical point/product-use/shot order. Each correlated frame retains
the original target frame and exact circuit acquisition provenance. Correlation
alone remains raw evidence. Before execution, the laboratory assigns each
mapped result address an `integrated_iq_shots(...)` or
`raw_trace_shots(...)` binding. `select_fake_measurement_realization` rejects
missing, duplicate, or unknown addresses and returns one canonical exact-cover
proof, so integrated-IQ and raw-trace results may coexist in the same target
batch without an order-dependent selector convention. Its `target` argument is
not an advisory descriptor: it must be the exact `FakeListTarget` whose target
identity and capability fingerprint match the compiled request.

Selection checks more than the requested value shape. For every address it
first verifies that the artifact sample rate equals the selected target sample
rate. It then recovers the prepared `Acquire` and the target-owned artifact
window and checks the exact entry/list position, scheduled program identity,
acquisition event identity, logical acquisition signal, acquisition kind,
target acquisition-channel binding, sample-grid start, and sample count. An
integrated-IQ binding additionally requires an observable `complex128` value
in `ratio` with canonical `[shot]` shape. A raw-trace binding requires the same
carrier with canonical `[shot, sample]` shape; its shot extent equals target
repetitions and its sample extent equals the checked artifact window.
`execute_realized_fake_measurements` consumes the sealed heterogeneous
selection, executes the compiled batch exactly once, and then realizes every
address under its own selected policy before closing all values together
through the core contract. It does not perform reduction, unit conversion,
dataset assembly, durable recording, or journal integration.

## Core Integration Boundary

Core authoring now has an explicit domain-neutral program seam.
`DomainProgramDef` carries a dialect identity, version, opaque body, typed
plan-stage inputs, and named result contracts; `DomainCall` binds those inputs
and results to hygienic values and logical products. The compiler retains that
identity through semantic verification, typed lowering, linking, point
materialization, coverage, and the durable run plan. Domain-produced products
have an explicit `DomainProductProducer`; authored measurement outputs have a
distinct `MeasurementTransformProductProducer`. A domain adapter claims exactly
one call. Core derives the call's source uses, its live transform closure,
derived output uses, and execution-task coverage from those producer edges. The
backend, not the adapter, establishes the durable call identity, including for
a zero-point execution.

The public adapter flow is deliberately two-stage. `select(DomainBatchView)`
inspects opaque program bodies, concrete per-point input values, typed result
contracts, exact product-use references, and recursively immutable product
contracts, then returns a `DomainExecutionOffer` naming one call and a
batch-capacity limit. An adapter cannot choose a result subset or manufacture
transform wiring. After validating competing offers and choosing a point batch,
the backend creates the exact `DomainBatchContext` and calls
`prepare(context)`. References from another context are rejected by the
context-bound preparation builder.

`scopecat-quantum` adds typed circuit handles and
`circuit_domain_program` / `circuit_domain_call` as its dialect-specific
bridge. The fake X-count adapter consumes the authored `Circuit` body and exact
`CircuitResult` acquisition slot rather than reconstructing a circuit or
selecting the first acquisition by convention. During preparation it uses
`context.new_preparation()` and the SDK refs carried by the selected call to
seal its circuit-target result mapping; the old materialized-plan result
mapping signature is no longer public.

The laboratory preparation boundary is now declarative. A laboratory adapter
can implement the complete synchronous point-local slice through the
`scopecat.sdk.domain` facade:

```text
DomainBatchView -> DomainExecutionOffer -> DomainBatchContext
    -> DomainPreparationBuilder.map_measurements(...) -> DomainResultMapping
    -> bind context.measurement_transforms to host implementations
    -> DomainPreparationBuilder.measurement_plan(...) -> DomainMeasurementPlan
    -> DomainPreparationBuilder.build(...) -> PreparedDomainExecution
```

`DomainResultMapping` exposes a public inventory instead of an opaque native
escape hatch. `target_entries` preserves target order, while `entries` and
`results` expose canonical logical order with exact `DomainPointRef` and
`DomainProductUseRef` capabilities. Address and logical-output lookups make
fan-out explicit without revealing compiler identities. A measurement plan
accepts explicit `DomainHostTransformBinding` selections for the core-minted
`DomainMeasurementTransform` values in the context. Each input port names one
exact consumer use; each output port carries its product contract and every
demanded downstream use, including an empty sibling output. The adapter chooses
only an implementation and must cover the context transform inventory exactly.
`build` then accepts only a
`DomainInvocationSpec`, `DomainTargetArtifactIdentity`, `DomainRuntime`, a
result realizer returning `DomainResultValue` values, and
`DomainResourceClaim` declarations. Core performs all lowering to value
fragments, transform graphs, invocation proofs, and execution resources.

The clean extension rule is therefore that laboratory code imports the domain
facade, not `scopecat.compiler`, `scopecat.sdk.domain.invocation`, internal
lowering helpers, or `Bound*`/`Closed*` stage values. `PreparedDomainExecution`
is an opaque accepted proof; its transient payload, runtime, realizer, value
fragments, and transform plan remain core-owned. The facade intentionally omits
durable submit/fetch/reconcile orchestration functions and submission-state
types.

Host-derived products use explicit authored transform dependency edges. The
fake example's generic domain call now declares only integrated-IQ acquisition;
a first-class binary-IQ transform produces the two probability products. Only
the probabilities are recorded, so reverse record demand keeps IQ acquisition
live through a hidden transform-input use. Domain calls remain independent and
unordered; ordered effects require explicit dependency edges and scheduler
semantics, not tuple position or adapter registration order.

Core now exposes two quantum-neutral prerequisites: target-neutral
logical-point materialization plus exact result identity mapping, and a
two-stage measurement-output boundary. The public builder lowers a
`DomainMeasurementPlan` to core's selected measurement outputs before effects.
After a correlated fetch, the adapter realizer returns one `DomainResultValue`
for every result address; core derives point/use/product identity, checks dtype,
unit, point-local axis shape, actual nested array structure, and typed array
leaves, revalidates mutable models, and snapshots accepted values in canonical
point/product-use order. The internal selected/closed carrier types are not
part of the laboratory SDK. This first measurement carrier accepts
observable products only and rejects axis-free `bool`/`string` products, which
have no `MeasurementValue` scalar representation; artifact and other payload
kinds require distinct closures. It does not inspect a quantum circuit, pulse
schedule, acquisition kind, or shot policy. The first version requires one
adapter entry per materialized logical point and exact coverage of the
core-derived source product-use inventory at every point. The inventory is
canonicalized to linked-plan use order; empty inventories and zero-point plans
still retain and check their selected product contracts. The unified execution
backend now proves
aggregate local/domain ownership and selects dynamic contiguous point batches
from adapter limits, user execution options, and point-local state barriers.
Cross-point value aggregation remains separate work.

The adapter declares one executable job independently of its output carrier
with `DomainInvocationSpec`. `DomainTargetArtifactIdentity` supplies target,
compiler, capability, artifact, and artifact-fingerprint facts; the invocation
adds a stable-content adapter intent and a transient target-owned payload. Core
binds those values to the exact result mapping and keeps the resulting closed
invocation private. Run identity and idempotency-key generation remain separate
runtime values. `DomainResourceClaim` uses the public `DomainResourceKind`
vocabulary; unified host orchestration lowers and checks the claims for overlap
and holds one lease across all local and domain batches. A string in an intent
fingerprint does not establish ownership. This keeps a future
artifact carrier or offloaded postprocessor from inheriting measurement-array
semantics merely because the first target returns measurements.

The provider-facing `DomainRuntime` ABI receives only core-minted
`DomainSubmitRequest`, `DomainFetchRequest`, and `DomainReconcileRequest`
values. It returns provider candidates through `DomainSubmitReceipt`,
`DomainFetchCandidate`/`DomainFetchReceipt`, and `DomainReconcileReceipt`.
The adapter never manufactures a submission identity and never drives durable
state transitions itself. Core owns Known/Uncertain/Absent state, retry
authorization, correlation, effect journaling, and the submit/fetch/reconcile
orchestration functions; those values and functions are absent from the public
facade. A result realizer receives only `CorrelatedDomainFetch`, which proves
receipt/job correlation, and must still verify the provider-specific result
fingerprint, count, and shape before returning SDK measurement values.
Submission is an `acquisition` effect; fetch/reconciliation are repeatable
`read` effects. Journal evidence contains intent, keys, job identity, receipt
hashes, status, and counts—not raw frames or accepted values.

The laboratory demo supplies the concrete first adapter. It submits an already
selected mixed realization, registers a job before calling the device primitive
so a lost response cannot replay the same idempotency key, and retains the raw
`FakeListRun` behind a job identity, and makes fetch/reconcile read-only. A
device exception that returns no run is retained as blocking unavailable
evidence and reconciles as unknown rather than permanent pending. Only
after a correlated fetch does it reuse the existing correlation and realization
proofs to produce canonical `DomainResultValue` declarations. The fake job
store and accepted values remain in memory. Core validates and closes those
values, strips target addresses into a producer-neutral fragment, and uses the
result mapping that was bound before submit. The preparation builder also owns
the typed pure host-transform graph before record projection. The fake module
authors that graph through `binary_iq_probability_transform`, while the adapter
only binds its context-owned transform ref to the host implementation.
The first executable slice is `POINT`: the demo sends integrated-IQ shots
through the domain-owned fragment as an unrecorded transform input, applies the
hardware-independent binary-IQ semantic transform once per canonical logical
point on the host, and seals `probability_0` and `probability_1` in a distinct
transform-owned fragment. Each semantic output is fanned out to every demanded
downstream use without repeating the kernel.
The current nearest-centroid realization is explicitly host-only: numerical
precision and rounding are not yet semantic, so no offload equivalence is
claimed. Final assembly feeds template-owned record aliases through independent
projection. Projected records then cross a receipt-bearing per-point committer:
each accepted receipt echoes the deterministic run/point operation and exact
chunk hash with a non-empty storage reference, while journal evidence omits
quantum result addresses, raw frames, and accepted values. Aliases remain fields
of one point record and do not cause additional writes. The demo uses the memory
committer to exercise this contract; dataset compaction and publication are
separate storage work. Trusted
reconstruction of sealed recovery states from durable journal evidence is not
yet implemented. There is no polling scheduler, chunking, cancellation, or
cross-process target job store. Authoring integration, aggregate
local/domain/transform ownership, local-engine collection, terminal
`RunOutcome`, and dataset publication now share the standard run lifecycle.
Backend-selected point batches are explicit, but general `POINT_SET` host
transforms, cross-point analysis, and adapter proofs that eligible transforms
have equivalent domain realizations remain later work. The notebook-facing
fake X-count path now uses the same capability-selecting domain adapter as the
mixed scalar-bias example; unrelated products continue through the virtual
point provider.

## Initial Non-Goals

- concrete AWG, digitizer, vendor, or laboratory schemas;
- QASM/QIR interchange compatibility;
- branch, feedback, arbitrary loops, or real-time classical control;
- a complete standard or native gate library;
- joint, multiplexed, or variable-cardinality measurement calibration;
- automatic multi-target partitioning or a general scheduler;
- durable serialization compatibility for transient quantum IR;
- experiment templates, calibration values, response models, or analysis
  workflows.
