# Quantum Domain Package Architecture

Status: accepted direction

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
      | laboratory target compiler   | exact core identity mapping
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

The batch also feeds a separate pure result-mapping boundary. Core first
materializes logical points from a `LinkedPlan` after a whole-program
relation-backend preflight, without selecting local Python compute or
instrument collection. The public `scopecat.domain_invocation` adapter SPI
then seals an opaque entry/result inventory against the complete canonical
logical-point and product-use
inventory. `scopecat-quantum` specializes that proof as
`CircuitTargetResultMapping`: target entries bind bijectively to logical
points, and each entry-qualified acquisition address binds to exactly one
product-use occurrence. Adapter ordering is retained as provenance but cannot
replace canonical logical output order. Record aliases remain downstream
projections and do not create acquisition work.

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
- one closed result mapping binds each target entry to one materialized logical
  point and each acquisition address to one exact product-use occurrence;
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
Scopecat logical points and proven result addresses to product-use identities.
Physical list and segment indices never replace either logical identity.
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

Core now exposes two quantum-neutral prerequisites: target-neutral
logical-point materialization plus sealed result identity mapping, and a
two-stage measurement-output boundary. `SelectedDomainMeasurementOutputs`
first proves before effects that every mapped product has a supported
measurement carrier. `ClosedDomainOutputValues` later derives point/use/product
identity from that selection, requires one value for every result address, checks
dtype, unit, point-local axis shape, actual nested array structure, and typed
array leaves, revalidates mutable models, then snapshots accepted values in
canonical point/product-use order. This first measurement carrier accepts
observable products only and rejects axis-free `bool`/`string` products, which
have no `MeasurementValue` scalar representation; artifact and other payload
kinds require distinct closures. It does not inspect a quantum circuit, pulse
schedule, acquisition kind, or shot policy. The first version requires one
adapter entry per materialized logical point and exact coverage of an explicit
selected product-use subset at every point. The subset is canonicalized to
linked-plan use order; empty subsets and zero-point plans still retain and check
their selected product contracts. The unified execution backend now proves
aggregate local/domain ownership and selects dynamic contiguous point batches
from adapter limits, user execution options, and point-local state barriers.
Cross-point value aggregation remains separate work.

Core now also closes one executable invocation independently of its output
carrier. `ClosedDomainInvocation` retains the exact result mapping plus an
adapter-owned transient payload, while its payload-free intent fingerprints
target, compiler, capability, artifact, logical result contract, and adapter
policy. Run identity and idempotency-key generation remain separate runtime
values. Prepared domain executions declare typed resource claims; unified host
orchestration checks them for overlap and holds one lease across all local and
domain batches. A string in an intent fingerprint does not establish
ownership. This keeps a future
artifact carrier or offloaded postprocessor from inheriting measurement-array
semantics merely because the first target returns measurements.

The host runtime ABI has explicit submit, fetch, and reconcile receipts, but
callers pass sealed states rather than trusting those candidates directly.
Submit returns Known; indeterminate errors carry Uncertain; definitive negative
evidence produces Absent. Fetch accepts only Known, reconcile accepts only
Uncertain, and a new submission-key generation requires Absent. Adapter fetch
payloads reach the adapter only after core returns `CorrelatedDomainFetch`.
That token proves receipt/job correlation; the adapter still verifies the
provider-specific result fingerprint, count, and shape. Submission
is an `acquisition` effect; fetch/reconciliation are repeatable `read` effects.
A known reconcile result closes the original unknown submit transition. Journal
evidence contains intent, keys, job identity, receipt hashes, status, and
counts—not raw frames or accepted values.

The laboratory demo supplies the concrete first adapter. It submits an already
selected mixed realization, registers a job before calling the device primitive
so a lost response cannot replay the same idempotency key, and retains the raw
`FakeListRun` behind a job identity, and makes fetch/reconcile read-only. A
device exception that returns no run is retained as blocking unavailable
evidence and reconciles as unknown rather than permanent pending. Only
after a correlated fetch does it reuse the existing correlation and value
closure to produce canonical `ClosedDomainOutputValues`. The fake job store
and accepted values remain in memory. Core then strips target addresses into a
producer-neutral fragment whose real domain result mapping was bound before
submit. A typed pure host-transform graph now sits before record projection.
The first executable slice is `POINT`: the demo sends only integrated-IQ shots
through the domain-owned fragment, applies the hardware-independent binary-IQ
semantic transform once per canonical logical point on the host, and seals
`probability_0` and `probability_1` in a distinct transform-owned fragment.
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
