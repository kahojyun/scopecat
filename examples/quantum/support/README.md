# Quantum Lab Demo Support Package

`quantum-lab-demo` is the installable support package behind
`examples/quantum`. It exists to show how a real lab can keep experiment
builders, virtual providers, reusable analysis steps, and fixture
models next to the notebooks that exercise them.

This package is not a stable domain extension. It is intentionally local demo
code used to validate Scopecat's notebook-first UX.

## What Lives Here

- experiment-system Rabi, simultaneous Rabi, manual and parameter-table background
  Rabi, readout-frequency, multiplexed readout, multiplexed readout calibration,
  single-qubit RB, CZ RB, CZ chevron, spectator-aware CZ, parallel gate-set,
  toy surface-code round, QND repeated measurement, and backend-batch modules
  and template entrypoints;
- a promoted `AnalysisStep` implementation for repeated readout-frequency
  analysis;
- domain calculation and plotting helpers behind that promoted analysis step;
- a unified virtual lab provider;
- a runnable fake AWG + digitizer domain adapter and reusable X-count reference;
- support-package unit tests.

## Where Users Customize

| Goal | Start here |
|---|---|
| Change reusable template inputs, default points, selected products, or seed inputs | `src/quantum_lab_demo/experiments/templates.py` |
| Add one-off point or parameter scans | `Workspace.prepare(...).input(...).scan(sc.cartesian(sc.axis(...), sc.param_axis(...))).preview()/run()` in notebooks |
| Reuse resource, state, compute, record, or product declarations | focused `src/quantum_lab_demo/experiments/*_modules.py` files |
| Generate point-local pulse programs | `src/quantum_lab_demo/experiments/compute.py`, with in-memory payload types in `src/quantum_lab_demo/experiments/payloads.py` |
| Edit lab wiring with qubit/coupler/line vocabulary | `quantum_wiring()`, `default_quantum_wiring()`, and `quantum_wiring_config_profile()` in `src/quantum_lab_demo/virtual_lab/wiring.py` |
| Inspect related readout cases | `../notebooks/08_readout_family.py` |
| Inspect surface-code-shaped and backend-batch cases | `../notebooks/09_system_scale_cases.py` |
| Compare reusable and scratch fake-hardware authoring | `../notebooks/10_fake_awg_template.py` and `../notebooks/11_fake_awg_scratch.py` |
| Inspect route-aware waveform compute | `../notebooks/07_gate_calibration_family.py` |
| Change workspace, config profile, or virtual profile paths | `src/quantum_lab_demo/lab.py` and `src/quantum_lab_demo/fixtures.py` |
| Replace virtual hardware with a real adapter | `src/quantum_lab_demo/virtual_lab/provider.py` |
| Keep domain calculations out of notebooks | `src/quantum_lab_demo/experiments/readout_analysis_calculations.py` |
| Turn notebook analysis into reusable code | `src/quantum_lab_demo/experiments/readout_analysis_steps.py` |
| Validate demo behavior | `tests/unit` and `../tests` |

Runnable user-facing examples live one directory up in `examples/quantum`.
Those examples should stay thin: they open `Workspace` objects, keep reusable
`ExperimentModule` declarations in focused domain files such as
`rabi_modules.py`, `readout_modules.py`, and `two_qubit_modules.py`. Products
live with the module that owns their logical resource instead of depending on
implicit same-name resource merging. Keep reusable `ExperimentTemplate`
entrypoints in `templates.py`; pass template constants directly to notebooks;
prepare or run them with fluent terminal calls such as
`Workspace.prepare(...).input(...).scan(...).preview()/run()`, inspect
`Run.data()`, save `Analysis`, try candidate configs, and review candidate run
comparisons.

Keep reusable declarations in module/template definitions when several users or
experiments share them. Scratch workspace experiments remain a supported way to
define one-off or locally composed work; the fake-hardware pair deliberately
keeps both forms executable and checks that they converge on one execution path.

The Rabi and CZ chevron modules intentionally return generated gate-sequence
and waveform payloads as ordinary in-memory Python objects. The CZ chevron
case combines scan variables with the `qubits` and
`two_qubit_gates` parameter tables inside compute functions, then
renders route-aware numpy waveform bundles for the virtual drive and coupler
stacks. The parallel gate-set and toy surface-code cases keep gate schedules
as ordinary in-memory Python objects while records remain dense arrays over
round, shot, entity, or backend-point axes. The runtime wraps those payloads
for instrument commands and emits compact compute summaries, including
dependency metadata for point columns, parameter tables, route ports, and
upstream compute nodes, without hashing arrays or requiring users to write
temporary waveform files.

The lab uses a small quantum wiring builder instead of requiring users
to hand-author the core routing graph. Users describe qubits, couplers, logical
lines, physical channels, and shared LO groups with `quantum_wiring()`, then
the helper validates those references and compiles that view into core
`Topology` lines/channels/groups plus routing channel bindings. Core stays
domain-neutral, while examples remain editable in terms a lab user would
recognize.

## Domain Package Boundary

`scopecat-quantum` now owns the hardware-independent gate, measurement,
circuit, pulse, schedule, calibration-selection, and target-compiler contracts.
This demo depends on that package and implements a concrete fake list-mode AWG
and segmented-digitizer target against those contracts, including an
end-to-end calibrated gate-plus-measurement example.

The demo continues to own laboratory wiring, calibration values, readout
workflows, virtual fixtures, response models, candidate activation policy, and
notebook examples. Those are laboratory concerns and do not move into the
foundational package.

## Fake List-Mode Target

`quantum_lab_demo.targets.fake_list_mode` provides an immutable target
configuration, a pure compiler, a fake list-mode AWG, and a segmented
digitizer runtime. Compilation requires exact sample-grid alignment and checks
logical-to-physical bindings, physical channel overlap, amplitude, list depth,
shot count, frame count, and waveform/capture memory before producing an
artifact.

The AWG repeats the complete ordered list for every shot. Every digitizer frame
retains its target entry, shot, acquisition slot, segment, and physical channel
identity; list and segment indices are never treated as logical identities.
Prepared circuit-target batches use the frame's entry-qualified acquisition
address to recover exact circuit and measurement provenance, including when
several list entries reuse the same circuit-local result slot. A
`CompiledCircuitTarget` first binds the compiled artifact back to that exact
batch and its logical point/product-use mapping. The demo then returns a
`CorrelatedFakeListRun` whose frames are canonically projected by logical point,
product-use occurrence, and shot while retaining the raw target-order run.
The first target supports `Constant` envelopes only. Gaussian and DRAG are
reported as unsupported target capabilities until their portable sampling
semantics are specified.

This runtime remains intentionally separate from the existing point-local
instrument provider. An explicit core domain-execution boundary now accepts its
prepared proof and publishes the result through the standard Run lifecycle.
The adapter is selected on each `Workspace.prepare(...)` call rather than on the
workspace, allowing local-provider and whole-program domain runs to share one
workspace without hidden target inheritance. Correlated frames remain raw evidence.
The v1 adapter contract is synchronous and whole-program: its first fetch must
be terminal. Pending or submit-uncertain outcomes are terminalized as
indeterminate Runs with durable target/artifact and reconciliation context;
automatic polling and resume are not claimed by this slice.
Callers explicitly bind every mapped result address with
`integrated_iq_shots(address)` or `raw_trace_shots(address)`; the two policies
may be freely mixed within one batch. `select_fake_measurement_realization`
rejects missing, duplicate, and unknown bindings, restores canonical logical
result order, and checks each product before effects. Its signature is
`select_fake_measurement_realization(compiled_target, target, bindings)`:
`target` must be the exact `FakeListTarget` selected by target identity and
capability fingerprint, and its sample rate must equal the compiled artifact's
sample rate. The proof also requires each prepared `Acquire` and artifact
window to agree on entry/list position, scheduled program, acquisition event,
logical signal, kind, target acquisition channel, sample-grid start, and sample
count.

Integrated-IQ bindings require observable `complex128` values in `ratio` with
canonical `[shot]` shape. Raw-trace bindings require canonical
`[shot, sample]` shape, with extents fixed by target repetitions and that
result's checked acquisition window. `execute_realized_fake_measurements`
executes the mixed target batch once, realizes each address under its selected
policy, and closes the heterogeneous values together while retaining the raw
frames.

For host-visible execution, `close_fake_measurement_invocation` closes the same
selection against target/compiler/capability/artifact evidence.
`FakeListDomainRuntime` gives an idempotent submission key one job identity,
registers that job before calling the device primitive, and makes fetch and
reconcile read-only. Core helpers journal submit as an
acquisition effect and fetch/reconcile as read effects; every receipt is
correlated to the complete closed intent. Callers pass sealed Known, Uncertain,
and Absent states rather than raw receipts; only a core-correlated
`CorrelatedDomainFetch` reaches adapter validation. Fetched raw runs still pass
through the existing correlation and realization proofs before values are
accepted. A device exception without a returned run remains an explicit
blocking unknown state rather than being reported as ordinary pending.
After lab-owned payload validation, closed domain values enter core's
producer-neutral fragment assembly through a result/carrier proof bound before
submit. An independent end-to-end fixture keeps integrated-IQ shots in that
domain-owned fragment, applies the hardware-independent binary-IQ transform as
one pure host `POINT` kernel call per logical point, and places
`probability_0`/`probability_1` only in a transform-owned fragment. Final exact
assembly then feeds template-owned projection and receipt-bearing point-record
commits. Aliases increase neither kernel calls nor physical record writes, and
journal evidence retains no target result addresses or raw frames.
The nearest-centroid reference remains host-only because numeric precision and
rounding are not yet part of its semantic contract.

The notebook-facing virtual provider still returns synthetic probability
products directly. That path predates typed measurement transforms and remains
legacy demo debt so the broader experiment catalog stays runnable during
migration. The X-count Template and scratch examples use the domain path and
produce standard durable Runs. `POINT_SET`, cross-point analysis, transform
authoring DSL, hidden intermediate products, local instrument-source migration,
offload equivalence, dataset compaction, polling, chunking, cancellation, and a
cross-process job store remain later work.

## Checks

From the repository root:

```sh
uv run --offline pytest examples/quantum/support/tests
uv run --offline ruff check examples/quantum/support
uv run --offline ruff format --check examples/quantum/support
uv run --offline basedpyright
```
